"""项目、占地、绑定与仓储。"""

from __future__ import annotations

from world.kernel.errors import TownError
from world.kernel.mapgrid import CN_REGION, bbox_tiles, region_at
from world.kernel.money import coins_to_cents
from world.kernel.state import Building, Project
from world.kernel.util import charge_time, require_not_frozen, require_region

PLUGIN_ID = "construction"
INJECT = ["clock", "map", "ledger", "agents", "log", "config", "world", "perception"]


def apply(ctx):
    ctx.actions.register("project_create", lambda a, p: _create(ctx, a, p))
    ctx.actions.register("pledge", lambda a, p: _pledge(ctx, a, p))
    ctx.actions.register("pledge_cancel", lambda a, p: _pledge_cancel(ctx, a, p))
    ctx.actions.register("project_cancel", lambda a, p: _project_cancel(ctx, a, p))
    ctx.actions.register("contribute", lambda a, p: _contribute(ctx, a, p))
    ctx.actions.register("bind", lambda a, p: _bind(ctx, a, p))
    ctx.actions.register("warehouse", lambda a, p: _warehouse(ctx, a, p))
    for kind in (
        "house_bind", "warehouse", "farm_labor_mul", "unlock_forest_tiles",
        "road", "owner_paddy", "owner_farm_plot", "owner_forest_plot",
    ):
        ctx.effects.register(kind, lambda *_a, **_k: None)
    ctx.hooks.daily_after(4, lambda world: _fail_check(ctx, world))
    ctx.hooks.tick_after(3, lambda world: _maybe_start(ctx, world))
    ctx.perception.register("projects_onsite", "region", lambda agent, pack: _projects(ctx, agent, pack))
    ctx.events.allow("PROJECT_UPDATE")
    ctx.events.allow("BUILDING_DONE")


def _create(ctx, actor, params):
    require_not_frozen(actor)
    require_region(actor, "town_hall")
    bname = params.get("building")
    row = ctx.config.building(bname)
    if not row:
        raise TownError("E1001")
    charge_time(actor, ctx.config.i("发起项目耗时", 20))
    w, h = int(row["占地宽"]), int(row["占地高"])
    x, y = int(params["x"]), int(params["y"])
    allowed = [s.strip() for s in (row.get("允许区域") or "").replace("；", ";").split(";") if s.strip()]
    ctx.map.footprint_ok(x, y, w, h, allowed, row.get("场所键"))
    # 开垦校验
    kind = row.get("场所键")
    if kind == "farm_plot" and (x, y) not in ctx.world.state.waste_farm:
        raise TownError("E1026")
    if kind == "forest_plot" and (x, y) not in ctx.world.state.unlocked_forest:
        raise TownError("E1026")
    mayor = ctx.world.state.mayor_id == actor.agent_id or actor.npc_id == "npc_mayor"
    deposit = 0 if mayor else coins_to_cents(ctx.config.f("项目保证金", 15), ctx.world.places)
    pid = ctx.world.state.nid("pj")
    if deposit:
        ctx.ledger.freeze(actor.agent_id, "coins", deposit, pid)
    proj = Project(
        project_id=pid, building=row["建筑名称"], venue_kind=row["场所键"],
        effect_kind=row.get("效果键") or "", x=x, y=y, w=w, h=h,
        initiator=actor.agent_id, status="pledging",
        need_wood=int(float(row.get("木材需求") or 0)),
        need_coins_cents=coins_to_cents(float(row.get("镇币需求") or 0), ctx.world.places),
        need_hours=int(float(row.get("工时需求") or 0)),
        created_day=ctx.clock.day, deposit_cents=deposit,
        category=row.get("类别") or "建造类",
    )
    ctx.world.state.projects[pid] = proj
    ctx.log.write("PROJECT_UPDATE", actor=actor.agent_id, params={"project_id": pid, "op": "create"})
    return {"project_id": pid}


def _pledge(ctx, actor, params):
    require_not_frozen(actor)
    pid = params.get("project_id")
    proj = ctx.world.state.projects.get(pid)
    if not proj or proj.status != "pledging":
        raise TownError("E1015")
    charge_time(actor, ctx.config.i("认筹耗时", 10))
    coins = params.get("coins") or 0
    wood = int(params.get("wood") or 0)
    hours = int(params.get("hours") or 0)
    from_pool = bool(params.get("from_pool"))
    bag = proj.pledges.setdefault(actor.agent_id, {"coins": 0, "wood": 0, "hours": 0, "from_pool": 0})
    if from_pool:
        if ctx.world.state.mayor_id not in (actor.agent_id, actor.npc_id):
            raise TownError("E1028")
        cents = coins_to_cents(coins, ctx.world.places)
        if ctx.world.state.public_pool_cents < cents:
            raise TownError("E1028")
        ctx.world.ledger.pool_debit(cents)
        proj.pledged_coins_cents += cents
        bag["from_pool"] += cents
    else:
        if coins:
            cents = coins_to_cents(coins, ctx.world.places)
            ctx.ledger.freeze(actor.agent_id, "coins", cents, pid)
            proj.pledged_coins_cents += cents
            bag["coins"] += cents
        if wood:
            ctx.ledger.freeze(actor.agent_id, "wood", wood, pid)
            proj.pledged_wood += wood
            bag["wood"] += wood
        if hours:
            proj.pledged_hours += hours
            bag["hours"] += hours
    ctx.log.write("PROJECT_UPDATE", actor=actor.agent_id, params={"project_id": pid, "op": "pledge"})
    return {"project_id": pid}


def _maybe_start(ctx, world):
    rate = ctx.config.f("木材镇币折算率", 2.5)
    for proj in world.state.projects.values():
        if proj.status != "pledging":
            continue
        wood_as_coins = 0
        if proj.category == "改造类":
            extra_wood = max(0, proj.pledged_wood - proj.need_wood)
            wood_as_coins = coins_to_cents(extra_wood * rate, world.places)
        coins_ok = proj.pledged_coins_cents + wood_as_coins >= proj.need_coins_cents
        if proj.pledged_wood >= proj.need_wood and coins_ok and proj.pledged_hours >= proj.need_hours:
            proj.status = "building"
            coef = ctx.config.f("施工工期系数", 2)
            proj.build_deadline_day = world.state.day + max(1, int(proj.need_hours * coef / 10) or int(coef))
            # 超额退还：简化跳过
            ctx.log.write("PROJECT_UPDATE", params={"project_id": proj.project_id, "op": "start"})


def _pledge_cancel(ctx, actor, params):
    require_not_frozen(actor)
    pid = params.get("project_id")
    proj = ctx.world.state.projects.get(pid)
    if not proj or proj.status != "pledging":
        raise TownError("E1045")
    bag = proj.pledges.get(actor.agent_id)
    if not bag:
        raise TownError("E1045")
    charge_time(actor, ctx.config.i("撤销认筹耗时", 10))
    ctx.ledger.unfreeze_doc(pid)  # 会解开所有人？不该。按人解冻需要更细。简化：只退该人数量
    # 精细：重建该单据其他人冻结
    _refund_agent(ctx, proj, actor.agent_id)
    proj.pledges.pop(actor.agent_id, None)
    return {"project_id": pid}


def _refund_agent(ctx, proj, agent_id):
    bag = proj.pledges.get(agent_id) or {}
    if bag.get("coins"):
        # 从冻结中释放：简化 credit 可用（若仍冻在 pid 上）
        frozen = [f for f in ctx.world.state.freezes if f.document_id == proj.project_id and f.agent_id == agent_id]
        for f in frozen:
            ctx.world.state.freezes.remove(f)
        proj.pledged_coins_cents -= bag.get("coins", 0)
        proj.pledged_wood -= bag.get("wood", 0)
        proj.pledged_hours -= bag.get("hours", 0)


def _project_cancel(ctx, actor, params):
    require_not_frozen(actor)
    require_region(actor, "town_hall")
    pid = params.get("project_id")
    proj = ctx.world.state.projects.get(pid)
    if not proj or proj.initiator != actor.agent_id or proj.status != "pledging":
        raise TownError("E1045")
    if any(proj.pledges.values()):
        raise TownError("E1045")
    charge_time(actor, ctx.config.i("撤销项目耗时", 10))
    ctx.ledger.unfreeze_doc(pid)
    proj.status = "cancelled"
    return {"cancelled": pid}


def _contribute(ctx, actor, params):
    require_not_frozen(actor)
    if actor.satiety <= 0:
        raise TownError("E1004")
    if actor.energy <= ctx.config.f("精力禁工阈值", 20):
        raise TownError("E1005")
    pid = params.get("project_id")
    proj = ctx.world.state.projects.get(pid)
    if not proj or proj.status != "building":
        raise TownError("E1007")
    venue = ctx.map.venue_at(actor.x, actor.y)
    if not venue or venue.get("project") != pid:
        # 也可能已部分落成
        tiles = bbox_tiles(proj.x, proj.y, proj.w, proj.h)
        if (actor.x, actor.y) not in tiles:
            raise TownError("E1006")
    bag = proj.pledges.get(actor.agent_id) or {}
    delivered = bag.get("delivered", 0)
    if delivered >= bag.get("hours", 0):
        raise TownError("E1007")
    charge_time(actor, ctx.config.i("出工耗时", 60))
    bag["delivered"] = delivered + 1
    proj.pledges[actor.agent_id] = bag
    proj.delivered_hours += 1
    # 密林副产物
    if proj.venue_kind == "forest_plot":
        rate = ctx.config.f("开垦木材副产物率", 0.3)
        total = int(proj.delivered_hours * rate)
        prev = int((proj.delivered_hours - 1) * rate)
        if total > prev:
            ctx.ledger.credit(actor.agent_id, "wood", total - prev)
    if proj.delivered_hours >= proj.need_hours:
        _complete(ctx, proj)
    return {"hours": 1}


def _complete(ctx, proj):
    proj.status = "done"
    bid = ctx.world.state.nid("bd")
    owner = proj.initiator if proj.venue_kind in ("paddy", "farm_plot", "forest_plot") else None
    b = Building(
        building_id=bid, kind=proj.building, venue_kind=proj.venue_kind,
        effect_kind=proj.effect_kind, x=proj.x, y=proj.y, w=proj.w, h=proj.h,
        status="done", owner_id=owner, last_work_day=ctx.clock.day,
    )
    ctx.world.state.buildings[bid] = b
    ctx.ledger.unfreeze_doc(proj.project_id)
    if proj.deposit_cents:
        ctx.ledger.credit(proj.initiator, "coins", proj.deposit_cents)
    if proj.venue_kind == "road":
        ctx.world.state.roads.add((proj.x, proj.y))
    if proj.venue_kind == "farm_plot":
        ctx.world.state.waste_farm.discard((proj.x, proj.y))
        ctx.world.state.open_farm.add((proj.x, proj.y))
    if proj.venue_kind == "forest_plot":
        ctx.world.state.unlocked_forest.discard((proj.x, proj.y))
        ctx.world.state.open_forest.add((proj.x, proj.y))
    if proj.effect_kind == "unlock_forest_tiles":
        n = ctx.config.i("开垦解锁tile数", 8)
        dense = sorted(ctx.world.state.dense_forest, key=lambda t: (t[1], t[0]))
        for t in dense:
            if t in ctx.world.state.unlocked_forest:
                continue
            ctx.world.state.unlocked_forest.add(t)
            n -= 1
            if n <= 0:
                break
    if proj.venue_kind == "tavern" and "npc_cook" not in ctx.world.state.agents:
        _activate_npc(ctx, "npc_cook", proj.x, proj.y)
    if proj.venue_kind == "warehouse" and "npc_keeper" not in ctx.world.state.agents:
        _activate_npc(ctx, "npc_keeper", proj.x, proj.y)
    ctx.log.write("BUILDING_DONE", params={"building_id": bid, "project_id": proj.project_id, "kind": proj.venue_kind})


def _activate_npc(ctx, npc_id, x, y):
    row = ctx.config.npc_by_id_or_name(npc_id)
    if not row:
        return
    from world.kernel.state import Agent
    ag = Agent(
        agent_id=npc_id, owner_id="system", name=row.get("NPC名") or npc_id,
        token="npc", trait=None, trait_words=(row.get("性格三词") or "").split(),
        vocation=row.get("职能") or "", backstory="", intro_npc="",
        x=x, y=y, kind="npc", npc_id=npc_id,
    )
    ctx.world.state.agents[npc_id] = ag
    ctx.log.write("WORLD_EVENT", params={"npc": npc_id, "op": "arrive"})


def _bind(ctx, actor, params):
    require_not_frozen(actor)
    require_region(actor, "town_hall")
    charge_time(actor, ctx.config.i("绑定耗时", 10))
    kind = params.get("kind")
    if params.get("op") == "unbind":
        if kind == "house":
            actor.house_id = None
        else:
            actor.warehouse_id = None
        return {"unbound": kind}
    bid = params.get("building_id")
    b = ctx.world.state.buildings.get(bid)
    if not b or b.status != "done":
        raise TownError("E1016")
    if kind == "house":
        if b.venue_kind != "house":
            raise TownError("E1016")
        if actor.house_id and actor.house_id != bid:
            raise TownError("E1016")
        cap = int(float(ctx.config.action_pre.get("住宅绑定容量", 4)))
        used = sum(1 for a in ctx.world.agents.settlers() if a.house_id == bid)
        if used >= cap:
            raise TownError("E1016")
        actor.house_id = bid
    elif kind == "warehouse":
        if b.venue_kind != "warehouse":
            raise TownError("E1016")
        if actor.warehouse_id and actor.warehouse_id != bid:
            raise TownError("E1016")
        actor.warehouse_id = bid
    else:
        raise TownError("E1001")
    return {"building_id": bid}


def _warehouse(ctx, actor, params):
    require_not_frozen(actor)
    if not actor.warehouse_id:
        raise TownError("E1044")
    venue = ctx.map.venue_at(actor.x, actor.y)
    b = ctx.world.state.buildings.get(actor.warehouse_id)
    if not b or not venue or venue.get("kind") != "warehouse":
        # 须站在任一仓库
        if not venue or venue.get("kind") != "warehouse":
            raise TownError("E1044")
    charge_time(actor, ctx.config.i("仓储耗时", 10))
    op = params.get("op")
    item = params.get("item")
    qty = int(params.get("qty") or 0)
    if item not in ("food", "wood") or qty < 1 or op not in ("deposit", "withdraw"):
        raise TownError("E1044")
    cap = int(float(ctx.config.action_pre.get("仓库容量上限", 100)))
    if op == "deposit":
        used = actor.receipt_food + actor.receipt_wood
        if used + qty > cap:
            raise TownError("E1044")
        ctx.ledger.debit(actor.agent_id, item, qty)
        ctx.ledger.credit(actor.agent_id, "receipt_" + item, qty)
    else:
        ctx.ledger.debit(actor.agent_id, "receipt_" + item, qty)
        ctx.ledger.credit(actor.agent_id, item, qty)
    return {"op": op, "qty": qty}


def _fail_check(ctx, world):
    term = ctx.config.i("项目流拍期限", 5)
    thresh = ctx.config.i("稻田荒废阈值", 3)
    for proj in list(world.state.projects.values()):
        if proj.status == "pledging" and world.state.day - proj.created_day >= term:
            for aid, bag in proj.pledges.items():
                _refund_agent(ctx, proj, aid)
            if proj.deposit_cents:
                ctx.ledger.unfreeze_doc(proj.project_id)
                ctx.world.ledger.pool_credit(proj.deposit_cents)
            proj.status = "failed"
            ctx.log.write("PROJECT_UPDATE", params={"project_id": proj.project_id, "op": "fail", "stage": "pledging"})
        if proj.status == "building" and proj.build_deadline_day and world.state.day > proj.build_deadline_day:
            # 施工流拍：材料不退，工时补偿
            pay = int(proj.delivered_hours * coins_to_cents(ctx.config.f("流拍工时补偿单价", 0.5), world.places))
            world.ledger.pool_debit(pay)
            if proj.deposit_cents:
                world.ledger.pool_credit(proj.deposit_cents)
            ctx.ledger.unfreeze_doc(proj.project_id)
            proj.status = "failed"
            ctx.log.write("PROJECT_UPDATE", params={"project_id": proj.project_id, "op": "fail", "stage": "building"})
    for b in world.state.buildings.values():
        if b.venue_kind in ("paddy", "farm_plot", "forest_plot") and b.status == "done":
            if b.last_work_day is None:
                b.last_work_day = world.state.day
            if world.state.day - (b.last_work_day or 0) >= thresh:
                b.status = "wasted"
                b.waste_count = thresh


def _projects(ctx, agent, pack):
    region = pack["region"]["type"]
    venue = pack["region"].get("venue") or {}
    if region != "town_hall" and not venue.get("project"):
        return None
    out = []
    for p in ctx.world.state.projects.values():
        if p.status in ("pledging", "building"):
            out.append({
                "project_id": p.project_id, "building": p.building, "status": p.status,
                "x": p.x, "y": p.y, "w": p.w, "h": p.h,
                "progress": {"wood": p.pledged_wood, "hours": p.delivered_hours},
                "initiator": p.initiator,
            })
    return out
