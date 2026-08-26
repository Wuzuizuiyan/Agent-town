"""悬赏：只订阅日志，不改 survival。"""

from __future__ import annotations

from world.kernel.errors import TownError
from world.kernel.money import coins_to_cents, cents_to_coins
from world.kernel.util import charge_time, require_not_frozen, require_region, season_of

PLUGIN_ID = "bounty"
INJECT = ["clock", "ledger", "agents", "log", "config", "world", "perception"]


def apply(ctx):
    ctx.actions.register("bounty_post", lambda a, p: _post(ctx, a, p))
    ctx.hooks.daily_after(5, lambda world: _payout(ctx, world))
    ctx.hooks.daily_after(7, lambda world: _routine_and_expire(ctx, world))
    ctx.perception.register("bounty_board", "region", lambda ag, pack: _board(ctx, pack))
    ctx.events.allow("BOUNTY")


def _post(ctx, actor, params):
    require_not_frozen(actor)
    require_region(actor, "town_hall")
    if ctx.world.state.mayor_id != actor.agent_id:
        raise TownError("E1042")
    typ = params.get("type")
    if typ not in ("labor", "build", "complete"):
        raise TownError("E1041")
    days = int(params.get("days") or 0)
    if days < 1 or days > ctx.config.i("悬赏期限上限", 3):
        raise TownError("E1041")
    cap = coins_to_cents(params.get("cap") or 0, ctx.world.places)
    charge_time(actor, ctx.config.i("发布悬赏耗时", 15))
    if len([b for b in ctx.world.state.bounties if b.get("status") == "active"]) >= ctx.config.i("悬赏榜容量上限", 10):
        raise TownError("E1042")
    bid = ctx.world.state.nid("by")
    ctx.world.state.bounties.append({
        "id": bid, "type": typ, "target": params.get("target"),
        "rate": float(params.get("rate") or ctx.config.f("悬赏_例行劳作单价", 0.15)),
        "cap_cents": cap, "remain_cents": cap,
        "expire_day": ctx.clock.day + days, "status": "active",
        "from": actor.agent_id,
    })
    ctx.log.write("BOUNTY", params={"id": bid, "op": "post"})
    return {"bounty_id": bid}


def _payout(ctx, world):
    yday = world.state.day - 1
    per_cap = coins_to_cents(ctx.config.f("每人日悬赏兑付上限", 2), world.places)
    per_one = coins_to_cents(ctx.config.f("每人单条悬赏日兑付上限", 1.5), world.places)
    paid_person = {}
    due = []  # (agent, cents, bounty)
    for b in world.state.bounties:
        if b.get("status") != "active":
            continue
        if b["type"] == "labor":
            for ev in world.state.events:
                if ev.day != yday or ev.type != "AGENT_ACTION":
                    continue
                if ev.params.get("action") != "work":
                    continue
                job = (ev.params.get("result") or {}).get("job")
                hours = (ev.params.get("result") or {}).get("hours") or 0
                target = b.get("target") or "farm"
                ok = (target in ("farm", "农夫") and job in ("farm", "paddy", "farm_plot")) or (
                    target in ("wood", "樵夫") and job in ("wood", "forest_plot")
                )
                if not ok:
                    continue
                cents = coins_to_cents(b["rate"] * hours, world.places)
                due.append((ev.actor, cents, b))
        elif b["type"] == "complete":
            for ev in world.state.events:
                if ev.day != yday or ev.type != "BUILDING_DONE":
                    continue
                if b.get("target") and ev.params.get("kind") != b.get("target"):
                    continue
                proj = world.state.projects.get(ev.params.get("project_id"))
                if proj:
                    due.append((proj.initiator, min(b["remain_cents"], b["cap_cents"]), b))
        elif b["type"] == "build":
            for ev in world.state.events:
                if ev.day != yday or ev.type != "PROJECT_UPDATE":
                    continue
                if ev.params.get("op") == "pledge" and ev.params.get("project_id") == b.get("target"):
                    due.append((ev.actor, coins_to_cents(b["rate"], world.places), b))
    # 限额压缩
    totals = {}
    for aid, cents, b in due:
        cents = min(cents, per_one, b["remain_cents"])
        used = paid_person.get(aid, 0)
        cents = min(cents, per_cap - used)
        if cents <= 0:
            continue
        totals.setdefault(aid, 0)
        totals[aid] += cents
        paid_person[aid] = used + cents
        b["remain_cents"] -= cents
        b.setdefault("_pay", []).append((aid, cents))
    need = sum(sum(c for _, c in b.get("_pay", [])) for b in world.state.bounties)
    pool = world.state.public_pool_cents
    ratio = 1.0 if need <= pool or need == 0 else pool / need
    add = ctx.config.f("声誉_悬赏加分", 0.05)
    for b in world.state.bounties:
        for aid, cents in b.pop("_pay", []):
            got = int(cents * ratio)
            world.ledger.pool_debit(got)
            a = world.state.agents.get(aid)
            if a:
                ctx.ledger.credit(aid, "coins", got)
                a.reputation = min(100, a.reputation + add * cents_to_coins(got, world.places))
            ctx.log.write("BOUNTY", params={"id": b["id"], "op": "pay", "to": aid, "cents": got})


def _routine_and_expire(ctx, world):
    for b in world.state.bounties:
        if b.get("status") == "active" and world.state.day > b.get("expire_day", 0):
            b["status"] = "expired"
    if world.state.mayor_id != "npc_mayor":
        return
    if any(b.get("from") == "npc_mayor" and b.get("status") == "active" and b.get("posted_day") == world.state.day for b in world.state.bounties):
        return
    season = season_of(world.state.day)
    cap = coins_to_cents(ctx.config.f("例行悬赏日限额", 6), world.places)
    typ, target, rate = "labor", "farm", ctx.config.f("悬赏_例行劳作单价", 0.15)
    if season != "harvest":
        pledging = [p for p in world.state.projects.values() if p.status == "pledging" and p.category == "建造类"]
        if pledging:
            typ, target, rate = "build", pledging[0].project_id, ctx.config.f("悬赏_例行认筹返现率", 0.05)
    world.state.bounties.append({
        "id": world.state.nid("by"), "type": typ, "target": target, "rate": rate,
        "cap_cents": cap, "remain_cents": cap, "expire_day": world.state.day + 1,
        "status": "active", "from": "npc_mayor", "posted_day": world.state.day,
    })
    ctx.log.write("BOUNTY", params={"op": "routine", "type": typ})


def _board(ctx, pack):
    if pack["region"]["type"] != "town_hall":
        return None
    return [
        {"id": b["id"], "type": b["type"], "target": b.get("target"),
         "rate": b.get("rate"), "remain": cents_to_coins(b.get("remain_cents", 0), ctx.world.places),
         "expire_day": b.get("expire_day"), "from": b.get("from")}
        for b in ctx.world.state.bounties if b.get("status") == "active"
    ]
