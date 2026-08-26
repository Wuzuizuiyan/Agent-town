"""公告、竞选、公投、执法。"""

from __future__ import annotations

from world.kernel.errors import TownError
from world.kernel.money import coins_to_cents, cents_to_coins
from world.kernel.util import charge_time, require_not_frozen, require_region

PLUGIN_ID = "governance"
INJECT = ["clock", "map", "ledger", "agents", "log", "config", "world", "perception", "rng"]


def apply(ctx):
    ctx.actions.register("bulletin_post", lambda a, p: _post(ctx, a, p))
    ctx.actions.register("election_create", lambda a, p: _election(ctx, a, p))
    ctx.actions.register("vote_election", lambda a, p: _vote_el(ctx, a, p))
    ctx.actions.register("plebiscite_create", lambda a, p: _pleb(ctx, a, p))
    ctx.actions.register("vote_plebiscite", lambda a, p: _vote_pl(ctx, a, p))
    ctx.actions.register("blueprint_propose", lambda a, p: _blueprint(ctx, a, p))
    ctx.actions.register("blueprint_support", lambda a, p: _support(ctx, a, p))
    ctx.effects.register("unlock_bulletin", lambda *_: None)
    ctx.effects.register("unlock_plebiscite", lambda *_: None)
    ctx.hooks.daily_after(7, lambda world: _daily(ctx, world))
    ctx.perception.register("bulletin_board", "region", lambda ag, pack: _p_bulletin(ctx, pack))
    ctx.perception.register("gov_board", "region", lambda ag, pack: _p_gov(ctx, pack))
    ctx.perception.register("reputation_board", "region", lambda ag, pack: _p_rep(ctx, pack))
    ctx.perception.register("blueprints", "region", lambda ag, pack: _p_bp(ctx, pack))
    ctx.perception.register("plebiscites", "region", lambda ag, pack: _p_pl(ctx, pack))
    ctx.events.allow("BULLETIN")
    ctx.events.allow("LAW")
    ctx.events.allow("ELECTION")
    ctx.events.allow("PLEBISCITE")
    ctx.events.allow("BLUEPRINT")


def _has_venue(ctx, kind) -> bool:
    return any(b.venue_kind == kind and b.status == "done" for b in ctx.world.state.buildings.values())


def _post(ctx, actor, params):
    require_not_frozen(actor)
    if not _has_venue(ctx, "bulletin"):
        raise TownError("E1024")
    venue = ctx.map.venue_at(actor.x, actor.y)
    if not venue or venue.get("kind") != "bulletin":
        raise TownError("E1024")
    content = params.get("content") or ""
    cap = int(float(ctx.config.action_pre.get("公告内容长度上限", 200)))
    if not content or len(content) > cap:
        raise TownError("E1024")
    today = [b for b in ctx.world.state.bulletins if b.get("day") == ctx.clock.day and b.get("actor") == actor.agent_id]
    if len(today) >= int(float(ctx.config.action_pre.get("公告每日张贴上限", 3))):
        raise TownError("E1024")
    charge_time(actor, ctx.config.i("张贴公告耗时", 10))
    fee = 0 if actor.rank == "elder" else coins_to_cents(ctx.config.f("公告张贴费", 2), ctx.world.places)
    if fee:
        ctx.ledger.debit(actor.agent_id, "coins", fee)
        ctx.world.ledger.pool_credit(fee)
    ctx.world.state.bulletins.append({
        "day": ctx.clock.day, "tick": ctx.clock.tick, "actor": actor.agent_id, "content": content, "system": False,
    })
    capn = int(float(ctx.config.action_pre.get("公告板容量上限", 30)))
    user = [b for b in ctx.world.state.bulletins if not b.get("system")]
    if len(user) > capn:
        oldest = next(b for b in ctx.world.state.bulletins if not b.get("system"))
        ctx.world.state.bulletins.remove(oldest)
    ctx.log.write("BULLETIN", actor=actor.agent_id)
    return {"posted": True}


def _election(ctx, actor, params):
    require_not_frozen(actor)
    require_region(actor, "town_hall")
    open_day = ctx.config.i("竞选开放日", 10)
    if ctx.clock.day < open_day:
        raise TownError("E1027")
    left = ctx.world.state.mayor_term_end - ctx.clock.day
    if left > ctx.config.i("竞选开放窗口", 2):
        raise TownError("E1027")
    if actor.kind != "settler" or ctx.clock.day - actor.enrolled_day < ctx.config.i("参选资历门槛", 5):
        raise TownError("E1027")
    if actor.loan_ban_until >= ctx.clock.day:
        raise TownError("E1027")
    charge_time(actor, ctx.config.i("发起竞选耗时", 20))
    if ctx.world.state.election and ctx.world.state.election.get("status") == "open":
        ctx.world.state.election["candidates"].append(actor.agent_id)
    else:
        ctx.world.state.election = {
            "status": "open", "candidates": [actor.agent_id], "votes": {}, "id": ctx.world.state.nid("el"),
        }
    ctx.log.write("ELECTION", params={"op": "create", "who": actor.agent_id})
    return {"election": True}


def _vote_el(ctx, actor, params):
    require_not_frozen(actor)
    el = ctx.world.state.election
    if not el or el.get("status") != "open":
        raise TownError("E1027")
    cid = params.get("candidate_id")
    if cid not in el["candidates"]:
        raise TownError("E1027")
    el["votes"][actor.agent_id] = cid
    return {"voted": cid}


def _pleb(ctx, actor, params):
    require_not_frozen(actor)
    require_region(actor, "town_hall")
    if not _has_venue(ctx, "hall"):
        raise TownError("E1033")
    motion = params.get("motion") or ""
    if not motion or len(motion) > int(float(ctx.config.action_pre.get("公投内容长度上限", 100))):
        raise TownError("E1033")
    charge_time(actor, ctx.config.i("发起公投耗时", 15))
    fee = coins_to_cents(float(ctx.config.action_pre.get("公投发起费", 3)), ctx.world.places)
    ctx.ledger.debit(actor.agent_id, "coins", fee)
    ctx.world.ledger.pool_credit(fee)
    pid = ctx.world.state.nid("pl")
    ctx.world.state.plebiscites[pid] = {
        "id": pid, "motion": motion, "from": actor.agent_id, "votes": {},
        "expire_day": ctx.clock.day + ctx.config.i("公投有效期", 3), "status": "open",
    }
    return {"plebiscite_id": pid}


def _vote_pl(ctx, actor, params):
    require_not_frozen(actor)
    pid = params.get("plebiscite_id")
    pl = ctx.world.state.plebiscites.get(pid)
    if not pl or pl["status"] != "open":
        raise TownError("E1034")
    ballot = params.get("ballot")
    if ballot not in ("yes", "no"):
        raise TownError("E1034")
    pl["votes"][actor.agent_id] = ballot
    return {"voted": ballot}


def _blueprint(ctx, actor, params):
    require_not_frozen(actor)
    require_region(actor, "town_hall")
    charge_time(actor, ctx.config.i("提案图纸耗时", 20))
    fee = coins_to_cents(float(ctx.config.action_pre.get("图纸提案费", 5)), ctx.world.places)
    ctx.ledger.debit(actor.agent_id, "coins", fee)
    ctx.world.ledger.pool_credit(fee)
    bid = ctx.world.state.nid("bp")
    ctx.world.state.blueprints[bid] = {
        "id": bid, "name": params.get("name"), "category": params.get("category"),
        "wood": params.get("wood"), "coins": params.get("coins"), "hours": params.get("hours"),
        "effect": params.get("effect"), "from": actor.agent_id, "supports": [],
        "status": "proposed", "expire_day": ctx.clock.day + ctx.config.i("图纸有效期", 5),
    }
    ctx.log.write("BLUEPRINT", params={"id": bid, "op": "propose"})
    return {"blueprint_id": bid}


def _support(ctx, actor, params):
    require_not_frozen(actor)
    bid = params.get("blueprint_id")
    bp = ctx.world.state.blueprints.get(bid)
    if not bp or bp["status"] != "proposed":
        raise TownError("E1032")
    if actor.agent_id == bp["from"] or actor.agent_id in bp["supports"] or actor.kind != "settler":
        raise TownError("E1032")
    bp["supports"].append(actor.agent_id)
    if len(bp["supports"]) >= ctx.config.i("图纸附议门槛", 3):
        bp["status"] = "review"
    return {"supports": len(bp["supports"])}


def _daily(ctx, world):
    # 任期计票
    el = world.state.election
    if el and el.get("status") == "open" and world.state.day > world.state.mayor_term_end:
        _tally(ctx, world, el)
    if world.state.day > world.state.mayor_term_end and (not el or el.get("status") != "open"):
        world.state.mayor_id = "npc_mayor"
        world.state.mayor_term_end = world.state.day + ctx.config.i("镇长任期", 7)
    # 执法
    _patrol(ctx, world)
    # 公投到期
    for pl in world.state.plebiscites.values():
        if pl["status"] == "open" and world.state.day > pl["expire_day"]:
            yes = sum(1 for v in pl["votes"].values() if v == "yes")
            no = sum(1 for v in pl["votes"].values() if v == "no")
            pl["status"] = "passed" if yes > no else ("void" if yes + no == 0 else "failed")
            ctx.log.write("PLEBISCITE", params={"id": pl["id"], "result": pl["status"], "yes": yes, "no": no})
    # 老镇拨款
    if world.state.mayor_id == "npc_mayor":
        _routine_grant(ctx, world)


def _tally(ctx, world, el):
    from collections import Counter
    votes = Counter(el["votes"].values())
    # NPC 票
    for npc in world.agents.npcs():
        if npc.npc_id in ("npc_guard", "npc_trader"):
            continue
        if npc.npc_id in ("npc_cook", "npc_keeper") and npc.npc_id not in world.state.agents:
            continue
        cands = [c for c in el["candidates"] if c in world.state.agents]
        if not cands:
            continue
        best = max(cands, key=lambda c: (world.state.npc_attitudes.get((npc.npc_id, c), 50), c))
        att = world.state.npc_attitudes.get((npc.npc_id, best), 50)
        p = (att / 100.0) * ctx.config.f("NPC投票概率系数", 0.5)
        rng = ctx.rng.stream("npc", el["id"], npc.npc_id, str(world.state.day))
        if rng.random() < p:
            votes[best] += 1
    if not votes:
        world.state.mayor_id = "npc_mayor"
    else:
        winner = sorted(votes.items(), key=lambda kv: (-kv[1], world.state.agents.get(kv[0], type("x", (), {"enrolled_day": 0})).enrolled_day, kv[0]))[0][0]
        world.state.mayor_id = winner
    el["status"] = "done"
    world.state.mayor_term_end = world.state.day + ctx.config.i("镇长任期", 7)
    ctx.log.write("ELECTION", params={"op": "tally", "mayor": world.state.mayor_id})


def _patrol(ctx, world):
    yday = world.state.day - 1
    for ev in world.state.events:
        if ev.day != yday:
            continue
        if ev.type == "LOAN_DEFAULT":
            _fine(ctx, ev.actor, ctx.config.f("执法罚款_失信", 10), "失信")
        if ev.type == "CONTRACT" and ev.params.get("op") == "breach":
            _fine(ctx, ev.params.get("by") or ev.actor, ctx.config.f("执法罚款_雇佣违约", 8), "雇佣")
        if ev.type == "PROJECT_UPDATE" and ev.params.get("op") == "fail" and ev.params.get("stage") == "building":
            proj = world.state.projects.get(ev.params.get("project_id"))
            if proj:
                _fine(ctx, proj.initiator, ctx.config.f("执法罚款_施工流拍", 15), "流拍")


def _fine(ctx, agent_id, amount, reason):
    a = ctx.world.state.agents.get(agent_id)
    if not a or a.kind != "settler":
        return
    cents = coins_to_cents(amount, ctx.world.places)
    take = min(cents, ctx.ledger.available(agent_id, "coins"))
    if take:
        ctx.ledger.debit(agent_id, "coins", take)
        ctx.world.ledger.pool_credit(take)
    a.mood -= ctx.config.f("处罚心情减益", 5)
    ctx.log.write("LAW", actor=agent_id, params={"reason": reason, "cents": take})


def _routine_grant(ctx, world):
    ratio = ctx.config.f("老镇拨款匹配比例", 0.5)
    cap = ctx.config.f("镇长拨款日限额", 20)
    pool_pct = ctx.config.f("镇长拨款池联动比例", 0.1)
    top = ctx.config.f("镇长拨款联动封顶", 50)
    pool_coins = cents_to_coins(world.state.public_pool_cents, world.places)
    limit_c = coins_to_cents(max(cap, min(pool_coins * pool_pct, top)), world.places)
    spent = 0
    for proj in sorted(world.state.projects.values(), key=lambda p: p.created_day):
        if proj.status != "pledging" or proj.category != "建造类":
            continue
        if proj.initiator == "npc_mayor":
            continue
        gap = max(0, proj.need_coins_cents - proj.pledged_coins_cents)
        match = min(int(proj.pledged_coins_cents * ratio), gap, limit_c - spent)
        if match <= 0:
            continue
        take = world.ledger.pool_debit(match)
        proj.pledged_coins_cents += take
        spent += take
        ctx.log.write("PROJECT_UPDATE", params={"op": "grant", "project_id": proj.project_id, "cents": take})


def _p_bulletin(ctx, pack):
    if pack["region"]["type"] != "town_hall":
        return None
    if not _has_venue(ctx, "bulletin"):
        return None
    return [{"actor": b["actor"], "content": b["content"], "tick": b["tick"]} for b in ctx.world.state.bulletins[-30:]]


def _p_gov(ctx, pack):
    if pack["region"]["type"] != "town_hall":
        return None
    el = ctx.world.state.election
    return {
        "mayor": ctx.world.state.mayor_id,
        "term_end": ctx.world.state.mayor_term_end,
        "election": None if not el else {"status": el.get("status"), "candidates": el.get("candidates")},
    }


def _p_rep(ctx, pack):
    if pack["region"]["type"] != "town_hall":
        return None
    rows = []
    for a in ctx.world.agents.settlers():
        rows.append({"agent_id": a.agent_id, "name": a.name, "score": a.reputation, "defaults": a.defaults, "rank": a.rank})
    rows.sort(key=lambda r: -r["score"])
    return rows


def _p_bp(ctx, pack):
    if pack["region"]["type"] != "town_hall":
        return None
    return [
        {"id": b["id"], "name": b["name"], "status": b["status"], "supports": len(b["supports"])}
        for b in ctx.world.state.blueprints.values() if b["status"] in ("proposed", "review")
    ]


def _p_pl(ctx, pack):
    if pack["region"]["type"] != "town_hall":
        return None
    if not _has_venue(ctx, "hall"):
        return None
    return [
        {"id": p["id"], "motion": p["motion"], "voted": len(p["votes"]), "status": p["status"]}
        for p in ctx.world.state.plebiscites.values() if p["status"] == "open"
    ]
