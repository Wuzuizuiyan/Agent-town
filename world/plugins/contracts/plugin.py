"""私交易、雇佣、工时委托、借贷、委托单、情报。"""

from __future__ import annotations

from world.kernel.errors import TownError
from world.kernel.mapgrid import region_at
from world.kernel.money import coins_to_cents, cents_to_coins
from world.kernel.state import Document
from world.kernel.util import charge_time, require_not_frozen

PLUGIN_ID = "contracts"
INJECT = ["clock", "map", "ledger", "agents", "log", "config", "world", "needs"]


def apply(ctx):
    ctx.actions.register("trade_private", lambda a, p: _trade(ctx, a, p))
    ctx.actions.register("trade_confirm", lambda a, p: _confirm(ctx, a, p, "trade"))
    ctx.actions.register("hire", lambda a, p: _hire(ctx, a, p))
    ctx.actions.register("hire_confirm", lambda a, p: _confirm(ctx, a, p, "hire"))
    ctx.actions.register("labor_transfer", lambda a, p: _labor(ctx, a, p))
    ctx.actions.register("labor_accept", lambda a, p: _confirm(ctx, a, p, "labor"))
    ctx.actions.register("loan", lambda a, p: _loan(ctx, a, p))
    ctx.actions.register("loan_confirm", lambda a, p: _confirm(ctx, a, p, "loan"))
    ctx.actions.register("guarantee_confirm", lambda a, p: _confirm(ctx, a, p, "guarantee"))
    ctx.actions.register("loan_repay", lambda a, p: _repay(ctx, a, p))
    ctx.actions.register("contract_terminate", lambda a, p: _terminate(ctx, a, p))
    ctx.actions.register("asset_transfer", lambda a, p: _asset(ctx, a, p))
    ctx.actions.register("transfer_confirm", lambda a, p: _confirm(ctx, a, p, "asset"))
    ctx.actions.register("standing_order", lambda a, p: _standing(ctx, a, p))
    ctx.actions.register("intel_share", lambda a, p: _intel(ctx, a, p))
    ctx.actions.register("intel_confirm", lambda a, p: _confirm(ctx, a, p, "intel"))
    ctx.hooks.tick_after(1, lambda world: _auto_eat(ctx, world))
    ctx.hooks.tick_after(3, lambda world: _timeouts(ctx, world))
    ctx.hooks.daily_after(6, lambda world: _credit(ctx, world))
    ctx.hooks.daily_after(7, lambda world: _expire_standing(ctx, world))
    ctx.events.allow("TRADE_PRIVATE")
    ctx.events.allow("CONTRACT")
    ctx.events.allow("LOAN")
    ctx.events.allow("LOAN_DEFAULT")
    ctx.events.allow("INTEL_SHARE")
    ctx.events.allow("STANDING_ORDER")
    ctx.events.allow("GUARANTEE")
    ctx.on_unload(lambda: _quiesce(ctx))


def _quiesce(ctx):
    for d in ctx.world.state.documents.values():
        if d.status in ("pending", "active") and d.kind in (
            "trade", "hire", "labor", "loan", "guarantee", "asset", "intel", "standing"
        ):
            d.status = "cancelled"
            ctx.ledger.unfreeze_doc(d.document_id)


def _rel_ok(ctx, a, b):
    rel = ctx.agents.relation(a.agent_id, b.agent_id)
    if rel.value < ctx.config.f("关系值拒绝门槛", -10):
        raise TownError("E1018")


def _peer(ctx, params):
    p = ctx.world.state.agents.get(params.get("peer_id"))
    if not p or p.kind != "settler":
        raise TownError("E1010")
    if p.frozen:
        raise TownError("E1010")
    return p


def _trade(ctx, actor, params):
    require_not_frozen(actor)
    if params.get("op") == "bargain":
        return _bargain(ctx, actor, params)
    peer = _peer(ctx, params)
    if region_at(actor.x, actor.y) != region_at(peer.x, peer.y):
        raise TownError("E1010")
    _rel_ok(ctx, actor, peer)
    item = params.get("item")
    qty = int(params.get("qty") or 0)
    price = params.get("price")
    if item not in ("food", "wood", "receipt_food", "receipt_wood") or qty < 1:
        raise TownError("E1001")
    if item.startswith("receipt") and region_at(actor.x, actor.y) != "town_hall":
        raise TownError("E1006")
    charge_time(actor, ctx.config.i("私交易发起耗时", 10))
    did = ctx.world.state.nid("dc")
    cents = coins_to_cents(price, ctx.world.places)
    ctx.ledger.freeze(actor.agent_id, item if item != "coins" else "food", qty, did)
    ctx.ledger.freeze(peer.agent_id, "coins", cents, did)
    ctx.world.state.documents[did] = Document(
        did, "trade",
        {"from": actor.agent_id, "to": peer.agent_id, "item": item, "qty": qty,
         "price_cents": cents, "bargains": 0},
        status="pending", created_tick=ctx.clock.tick,
        expire_tick=ctx.clock.tick + int(float(ctx.config.action_pre.get("私交易确认时限", 12))),
    )
    _notice(ctx, peer.agent_id, "trade_notices", {"document_id": did, "op": "trade"})
    return {"document_id": did}


def _bargain(ctx, actor, params):
    did = params.get("document_id")
    doc = ctx.world.state.documents.get(did)
    if not doc or doc.kind != "trade" or doc.status != "pending":
        raise TownError("E1019")
    cap = int(float(ctx.config.action_pre.get("私交易改价次数上限", 3)))
    if doc.payload["bargains"] >= cap:
        raise TownError("E1019")
    new_p = coins_to_cents(params.get("price"), ctx.world.places)
    old = doc.payload["price_cents"]
    if old <= 0 or abs(new_p - old) / old < float(ctx.config.action_pre.get("还价最小调价幅度", 0.05)):
        raise TownError("E1019")
    doc.payload["price_cents"] = new_p
    doc.payload["bargains"] += 1
    return {"document_id": did, "price": cents_to_coins(new_p, ctx.world.places)}


def _hire(ctx, actor, params):
    require_not_frozen(actor)
    peer = _peer(ctx, params)
    _rel_ok(ctx, actor, peer)
    days = int(params.get("days") or 0)
    wage = params.get("wage_per_hour")
    hours = int(params.get("hours_total") or 0)
    cap = ctx.config.i("雇佣日交付上限", 12)
    if days < 1 or hours < 1 or hours > days * cap:
        raise TownError("E1001")
    charge_time(actor, ctx.config.i("雇佣发起耗时", 15))
    opts = params.get("contract_options") or {}
    did = ctx.world.state.nid("ct")
    if opts.get("profit_share"):
        typ = "profit_share"
        freeze = 0
    else:
        typ = "fixed_wage"
        freeze = coins_to_cents(float(wage) * hours, ctx.world.places)
        ctx.ledger.freeze(actor.agent_id, "coins", freeze, did)
    if opts.get("bonus_amount"):
        bonus = coins_to_cents(opts["bonus_amount"], ctx.world.places)
        ctx.ledger.freeze(actor.agent_id, "coins", bonus, did + ":bonus")
    ctx.world.state.documents[did] = Document(
        did, "hire",
        {"employer": actor.agent_id, "worker": peer.agent_id, "days": days,
         "hours_total": hours, "hours_delivered": 0, "wage_cents": coins_to_cents(wage or 0, ctx.world.places),
         "type": typ, "profit_share": float(opts.get("profit_share") or 0),
         "exclusive": bool(opts.get("exclusive")),
         "due_day": None},
        status="pending", created_tick=ctx.clock.tick,
        expire_tick=ctx.clock.tick + ctx.config.i("雇佣确认时限", 12),
    )
    _notice(ctx, peer.agent_id, "trade_notices", {"document_id": did, "op": "hire"})
    return {"document_id": did}


def _labor(ctx, actor, params):
    require_not_frozen(actor)
    peer = _peer(ctx, params)
    _rel_ok(ctx, actor, peer)
    pid = params.get("project_id")
    hours = int(params.get("hours") or 0)
    wage = float(params.get("wage_per_hour") or 0)
    proj = ctx.world.state.projects.get(pid)
    if not proj:
        raise TownError("E1020")
    bag = proj.pledges.get(actor.agent_id) or {}
    left = bag.get("hours", 0) - bag.get("delivered", 0)
    if hours < 1 or hours > left:
        raise TownError("E1001")
    charge_time(actor, ctx.config.i("工时委托发起耗时", 15))
    did = ctx.world.state.nid("ct")
    freeze = coins_to_cents(wage * hours, ctx.world.places) if wage else 0
    if freeze:
        ctx.ledger.freeze(actor.agent_id, "coins", freeze, did)
    ctx.world.state.documents[did] = Document(
        did, "labor",
        {"from": actor.agent_id, "to": peer.agent_id, "project_id": pid,
         "hours": hours, "wage_cents": coins_to_cents(wage, ctx.world.places)},
        status="pending", created_tick=ctx.clock.tick,
        expire_tick=ctx.clock.tick + int(float(ctx.config.action_pre.get("工时委托确认时限", 12))),
    )
    return {"document_id": did}


def _loan(ctx, actor, params):
    require_not_frozen(actor)
    if actor.loan_ban_until >= ctx.clock.day:
        raise TownError("E1030")
    peer = _peer(ctx, params)
    _rel_ok(ctx, actor, peer)
    principal = coins_to_cents(params.get("principal"), ctx.world.places)
    rate = float(params.get("rate") or 0)
    days = int(params.get("days") or 0)
    if rate > ctx.config.f("借贷利率上限", 0.2) or days > ctx.config.i("借贷期限上限", 14) or days < 1:
        raise TownError("E1021")
    rec = params.get("receipt") or {}
    item = rec.get("item")
    qty = int(rec.get("qty") or 0)
    if item not in ("food", "wood") or qty < 1:
        raise TownError("E1021")
    charge_time(actor, ctx.config.i("借贷发起耗时", 15))
    # 抵押计值
    if item == "wood":
        val = coins_to_cents(qty * ctx.config.f("木材镇币折算率", 2.5), ctx.world.places)
    else:
        val = qty * ctx.world.state.anchors["food"]
    disc = ctx.config.f("声誉优惠抵押折扣", 0.85) if actor.reputation >= ctx.config.f("声誉优惠门槛", 70) else ctx.config.f("抵押折算折扣", 0.7)
    interest = int(principal * rate)
    if val * disc < principal + interest:
        raise TownError("E1021")
    did = ctx.world.state.nid("ln")
    ctx.ledger.freeze(actor.agent_id, "receipt_" + item, qty, did)
    opts = params.get("contract_options") or {}
    ctx.world.state.documents[did] = Document(
        did, "loan",
        {"borrower": actor.agent_id, "lender": peer.agent_id, "principal_cents": principal,
         "rate": rate, "days": days, "receipt_item": item, "receipt_qty": qty,
         "guarantor": opts.get("guarantor_id"), "g_ok": not opts.get("guarantor_id"),
         "interest_cents": interest},
        status="pending", created_tick=ctx.clock.tick,
        expire_tick=ctx.clock.tick + int(float(ctx.config.action_pre.get("私交易确认时限", 12))),
    )
    if opts.get("guarantor_id"):
        _notice(ctx, opts["guarantor_id"], "trade_notices", {"document_id": did, "op": "guarantee"})
    else:
        _notice(ctx, peer.agent_id, "trade_notices", {"document_id": did, "op": "loan"})
    return {"document_id": did}


def _asset(ctx, actor, params):
    require_not_frozen(actor)
    peer = _peer(ctx, params)
    _rel_ok(ctx, actor, peer)
    bid = params.get("asset_id")
    b = ctx.world.state.buildings.get(bid)
    if not b or b.owner_id != actor.agent_id or b.status != "done":
        raise TownError("E1025")
    charge_time(actor, ctx.config.i("属主转让发起耗时", 15))
    price = coins_to_cents(params.get("price") or 0, ctx.world.places)
    fee = coins_to_cents(float(ctx.config.action_pre.get("属主转让过户费", 2)), ctx.world.places)
    did = ctx.world.state.nid("dc")
    ctx.ledger.freeze(peer.agent_id, "coins", price + fee, did)
    ctx.world.state.documents[did] = Document(
        did, "asset",
        {"from": actor.agent_id, "to": peer.agent_id, "asset_id": bid,
         "price_cents": price, "fee_cents": fee, "waste": b.waste_count},
        status="pending", created_tick=ctx.clock.tick,
        expire_tick=ctx.clock.tick + int(float(ctx.config.action_pre.get("转让确认时限", 12))),
    )
    return {"document_id": did}


def _standing(ctx, actor, params):
    require_not_frozen(actor)
    active = [d for d in ctx.world.state.documents.values()
              if d.kind == "standing" and d.status == "active" and d.payload.get("agent_id") == actor.agent_id]
    cap = ctx.config.i("委托单并发上限", 3)
    if actor.rank in ("good_neighbor", "notable", "elder"):
        cap += ctx.config.i("良民委托单加成", 2)
    if len(active) >= cap:
        raise TownError("E1037")
    typ = params.get("type")
    days = int(params.get("days") or 0)
    if typ not in ("limit_buy", "limit_sell", "auto_eat") or days < 1 or days > ctx.config.i("委托单有效期上限", 7):
        raise TownError("E1038")
    charge_time(actor, ctx.config.i("设置委托单耗时", 10))
    did = ctx.world.state.nid("so")
    payload = {"agent_id": actor.agent_id, "type": typ, "expire_day": ctx.clock.day + days,
               "qty": int(params.get("qty") or 1)}
    if typ == "auto_eat":
        th = int(params.get("satiety_threshold") or 0)
        if th > ctx.config.f("条件进食饱食阈值上限", 40):
            raise TownError("E1038")
        qty = int(params.get("qty") or 1)
        ctx.ledger.freeze(actor.agent_id, "food", qty, did)
        payload.update({"satiety_threshold": th, "qty": qty, "frozen": {"food": qty}})
    else:
        item = params.get("item")
        price = coins_to_cents(params.get("price"), ctx.world.places)
        payload.update({"item": item, "price_cents": price})
        if typ == "limit_buy":
            tax = ctx.config.f("市集税率", 0.08)
            lock = int(payload["qty"] * price * (1 + tax))
            ctx.ledger.freeze(actor.agent_id, "coins", lock, did)
            payload["frozen"] = {"coins": cents_to_coins(lock, ctx.world.places)}
        else:
            ctx.ledger.freeze(actor.agent_id, item, payload["qty"], did)
            payload["frozen"] = {item: payload["qty"]}
    ctx.world.state.documents[did] = Document(did, "standing", payload, status="active",
                                              created_tick=ctx.clock.tick)
    ctx.log.write("STANDING_ORDER", actor=actor.agent_id, params={"id": did, "type": typ})
    return {"order_id": did}


def _intel(ctx, actor, params):
    require_not_frozen(actor)
    peer = _peer(ctx, params)
    cap = ctx.config.i("每tick情报分享上限", 2)
    if actor.intel_this_tick >= cap:
        raise TownError("E1001")
    region = params.get("region")
    price = float(params.get("price") or 0)
    snap = actor.last_region_snapshot.get(region)
    if not snap:
        raise TownError("E1001")
    same = region_at(actor.x, actor.y) == region_at(peer.x, peer.y)
    rel = ctx.agents.relation(actor.agent_id, peer.agent_id)
    if not same and rel.value < ctx.config.f("情报分享关系门槛", 20) and actor.rank not in (
        "good_neighbor", "notable", "elder"
    ):
        raise TownError("E1018")
    charge_time(actor, ctx.config.i("情报分享发起耗时", 10))
    actor.intel_this_tick += 1
    if price <= 0:
        _deliver_intel(ctx, peer.agent_id, actor, region, snap, 0)
        return {"gift": True}
    did = ctx.world.state.nid("dc")
    ctx.world.state.documents[did] = Document(
        did, "intel",
        {"from": actor.agent_id, "to": peer.agent_id, "region": region, "snap": snap,
         "price_cents": coins_to_cents(price, ctx.world.places)},
        status="pending", created_tick=ctx.clock.tick,
        expire_tick=ctx.clock.tick + int(float(ctx.config.action_pre.get("情报确认时限", 6))),
    )
    return {"document_id": did}


def _deliver_intel(ctx, to, src, region, snap, price):
    ttl = ctx.config.i("情报有效期", 24)
    fresh = "fresh" if ctx.clock.tick - snap.get("tick", 0) <= ttl else "stale"
    ctx.world.state.inbox.setdefault(to, {
        "unread_dialogues": [], "trade_notices": [], "pledge_notices": [],
        "intel_shares": [], "gm_facts": [],
    })["intel_shares"].append({
        "source_agent": src.agent_id, "source_tick": snap.get("tick"),
        "price": price, "region": region, "freshness": fresh, "snapshot": snap,
    })


def _confirm(ctx, actor, params, kind):
    require_not_frozen(actor)
    did = params.get("document_id")
    doc = ctx.world.state.documents.get(did)
    if not doc or doc.status != "pending":
        raise TownError("E1009" if kind != "intel" else "E1040")
    if ctx.clock.tick > doc.expire_tick:
        doc.status = "cancelled"
        ctx.ledger.unfreeze_doc(did)
        raise TownError("E1040" if kind == "intel" else "E1009")
    p = doc.payload
    if kind == "trade":
        if actor.agent_id != p["to"]:
            raise TownError("E1010")
        ctx.ledger.consume_frozen(did, p["from"], p["item"], p["qty"])
        ctx.ledger.consume_frozen(did, p["to"], "coins", p["price_cents"])
        ctx.ledger.credit(p["to"], p["item"], p["qty"])
        ctx.ledger.credit(p["from"], "coins", p["price_cents"])
        doc.status = "done"
        ctx.log.write("TRADE_PRIVATE", actor=actor.agent_id, params={"id": did})
    elif kind == "hire":
        if actor.agent_id != p["worker"]:
            raise TownError("E1020")
        if p.get("exclusive") and not params.get("accept_exclusive"):
            raise TownError("E1020")
        p["due_day"] = ctx.clock.day + p["days"]
        doc.status = "active"
        ctx.log.write("CONTRACT", params={"id": did, "op": "confirm"})
    elif kind == "labor":
        if actor.agent_id != p["to"]:
            raise TownError("E1020")
        proj = ctx.world.state.projects[p["project_id"]]
        src = proj.pledges.get(p["from"], {})
        src["hours"] = src.get("hours", 0) - p["hours"]
        dst = proj.pledges.setdefault(p["to"], {"coins": 0, "wood": 0, "hours": 0, "delivered": 0})
        dst["hours"] += p["hours"]
        doc.status = "done"
    elif kind == "guarantee":
        if actor.agent_id != p.get("guarantor"):
            raise TownError("E1021")
        cap = int(p["principal_cents"] * ctx.config.f("担保补偿上限比例", 0.5))
        ctx.ledger.freeze(actor.agent_id, "coins", cap, did + ":g")
        p["g_ok"] = True
        _notice(ctx, p["lender"], "trade_notices", {"document_id": did, "op": "loan"})
        return {"guaranteed": True}
    elif kind == "loan":
        if actor.agent_id != p["lender"]:
            raise TownError("E1021")
        if not p.get("g_ok"):
            raise TownError("E1021")
        borrower = ctx.world.state.agents[p["borrower"]]
        if borrower.loan_ban_until >= ctx.clock.day:
            raise TownError("E1030")
        ctx.ledger.debit(actor.agent_id, "coins", p["principal_cents"])
        ctx.ledger.credit(p["borrower"], "coins", p["principal_cents"])
        p["due_day"] = ctx.clock.day + p["days"]
        p["start_day"] = ctx.clock.day
        doc.status = "active"
        ctx.log.write("LOAN", params={"id": did, "op": "confirm"})
    elif kind == "asset":
        if actor.agent_id != p["to"]:
            raise TownError("E1025")
        b = ctx.world.state.buildings[p["asset_id"]]
        ctx.ledger.consume_frozen(did, p["to"], "coins", p["price_cents"] + p["fee_cents"])
        ctx.ledger.credit(p["from"], "coins", p["price_cents"])
        ctx.world.ledger.pool_credit(p["fee_cents"])
        b.owner_id = p["to"]
        doc.status = "done"
    elif kind == "intel":
        if actor.agent_id != p["to"]:
            raise TownError("E1040")
        ctx.ledger.debit(actor.agent_id, "coins", p["price_cents"])
        ctx.ledger.credit(p["from"], "coins", p["price_cents"])
        src = ctx.world.state.agents[p["from"]]
        _deliver_intel(ctx, actor.agent_id, src, p["region"], p["snap"],
                       cents_to_coins(p["price_cents"], ctx.world.places))
        doc.status = "done"
        ctx.log.write("INTEL_SHARE", params={"id": did})
    else:
        raise TownError("E1001")
    return {"document_id": did, "status": doc.status}


def _repay(ctx, actor, params):
    require_not_frozen(actor)
    lid = params.get("loan_id") or params.get("document_id")
    doc = ctx.world.state.documents.get(lid)
    if not doc or doc.kind != "loan" or doc.status != "active":
        raise TownError("E1022")
    held_days = max(1, ctx.clock.day - (doc.payload.get("start_day") or ctx.clock.day - 1))
    interest = int(doc.payload["principal_cents"] * doc.payload["rate"] * held_days / max(1, doc.payload["days"]))
    total = doc.payload["principal_cents"] + interest
    ctx.ledger.debit(actor.agent_id, "coins", total)
    ctx.ledger.credit(doc.payload["lender"], "coins", total)
    ctx.ledger.unfreeze_doc(lid)
    ctx.ledger.unfreeze_doc(lid + ":g")
    doc.status = "done"
    return {"repaid": lid}


def _terminate(ctx, actor, params):
    require_not_frozen(actor)
    cid = params.get("contract_id")
    doc = ctx.world.state.documents.get(cid)
    if not doc or doc.kind != "hire" or doc.status != "active":
        raise TownError("E1020")
    if actor.agent_id not in (doc.payload["employer"], doc.payload["worker"]):
        raise TownError("E1020")
    ctx.ledger.unfreeze_doc(cid)
    doc.status = "terminated"
    actor.defaults += 1
    actor.mood -= ctx.config.f("违约心情减益", 4)
    ctx.log.write("CONTRACT", params={"id": cid, "op": "breach", "by": actor.agent_id})
    return {"terminated": cid}


def _timeouts(ctx, world):
    for d in world.state.documents.values():
        if d.status == "pending" and d.expire_tick and world.state.tick > d.expire_tick:
            d.status = "cancelled"
            ctx.ledger.unfreeze_doc(d.document_id)


def _auto_eat(ctx, world):
    for d in world.state.documents.values():
        if d.kind != "standing" or d.status != "active":
            continue
        p = d.payload
        if p.get("type") != "auto_eat":
            continue
        a = world.state.agents.get(p["agent_id"])
        if not a:
            continue
        if a.satiety <= p.get("satiety_threshold", 0) and p.get("qty", 0) > 0:
            try:
                ctx.ledger.consume_frozen(d.document_id, a.agent_id, "food", 1)
            except TownError:
                continue
            a.satiety += ctx.config.f("进食饱食恢复", 10)
            p["qty"] -= 1
            if p["qty"] <= 0:
                d.status = "done"


def _credit(ctx, world):
    for d in list(world.state.documents.values()):
        if d.kind == "loan" and d.status == "active" and d.payload.get("due_day", 9999) <= world.state.day:
            p = d.payload
            total = p["principal_cents"] + p["interest_cents"]
            borrower = world.state.agents.get(p["borrower"])
            try:
                ctx.ledger.debit(p["borrower"], "coins", total)
                ctx.ledger.credit(p["lender"], "coins", total)
                ctx.ledger.unfreeze_doc(d.document_id)
                d.status = "done"
            except TownError:
                ctx.ledger.unfreeze_doc(d.document_id)
                qty = p["receipt_qty"]
                if borrower:
                    item = "receipt_" + p["receipt_item"]
                    held = ctx.ledger._held(borrower.agent_id, item)
                    take = min(held, qty)
                    if take:
                        ctx.ledger._set(borrower.agent_id, item, held - take)
                        ctx.ledger.credit(p["lender"], item, take)
                if borrower:
                    borrower.defaults += 1
                    borrower.mood -= ctx.config.f("违约心情减益", 4)
                    borrower.loan_ban_until = world.state.day + ctx.config.i("失信禁借期", 7)
                d.status = "defaulted"
                ctx.log.write("LOAN_DEFAULT", actor=p["borrower"], params={"id": d.document_id})
        if d.kind == "hire" and d.status == "active" and d.payload.get("due_day", 9999) <= world.state.day:
            ctx.ledger.unfreeze_doc(d.document_id)
            d.status = "done"
    # 声誉粗算
    window = ctx.config.i("声誉统计窗口", 14)
    base = ctx.config.f("声誉基础分", 50)
    for a in world.agents.settlers():
        score = base - a.defaults * ctx.config.f("声誉_违约扣分", 8)
        a.reputation = max(0, min(100, score))
        from world.kernel.util import rank_of
        a.rank = rank_of(a.reputation, ctx.config)


def _expire_standing(ctx, world):
    for d in world.state.documents.values():
        if d.kind == "standing" and d.status == "active" and d.payload.get("expire_day", 0) < world.state.day:
            d.status = "cancelled"
            ctx.ledger.unfreeze_doc(d.document_id)


def _notice(ctx, agent_id, bucket, payload):
    box = ctx.world.state.inbox.setdefault(agent_id, {
        "unread_dialogues": [], "trade_notices": [], "pledge_notices": [],
        "intel_shares": [], "gm_facts": [],
    })
    box[bucket].append(payload)
