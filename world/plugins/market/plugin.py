"""市集撮合与阿市系统供给。"""

from __future__ import annotations

from world.kernel.errors import TownError
from world.kernel.money import coins_to_cents, cents_to_coins
from world.kernel.state import Order
from world.kernel.util import charge_time, require_not_frozen, require_region

PLUGIN_ID = "market"
INJECT = ["clock", "map", "ledger", "agents", "log", "config", "world", "perception"]


def apply(ctx):
    ctx.actions.register("order_place", lambda a, p: _place(ctx, a, p))
    ctx.actions.register("order_cancel", lambda a, p: _cancel(ctx, a, p))
    ctx.hooks.tick_after(4, lambda world: _match(ctx, world))
    ctx.hooks.daily_after(3, lambda world: _restock(ctx, world))
    ctx.perception.register("market_board", "region", lambda agent, pack: _board(ctx, agent, pack))
    ctx.perception.register("market_summary", "region", lambda agent, pack: _summary(ctx, agent, pack))
    ctx.events.allow("TRADE_MATCH")
    ctx.on_unload(lambda: _quiesce(ctx))


def _quiesce(ctx):
    st = ctx.world.state
    keep = []
    for o in st.orders:
        ctx.ledger.unfreeze_doc(o.order_id)
        # 解冻后单据作废
    st.orders = keep


def _anchor(ctx, item: str) -> int:
    return ctx.world.state.anchors.get(item, 200)


def _place(ctx, actor, params):
    require_not_frozen(actor)
    require_region(actor, "market")
    item = params.get("item")
    side = params.get("side")
    qty = int(params.get("qty") or 0)
    price = params.get("price")
    days = int(params.get("days") or 1)
    if item not in ("food", "wood") or side not in ("buy", "sell") or qty < 1 or price is None:
        raise TownError("E1001")
    charge_time(actor, ctx.config.i("挂单耗时", 10))
    price_cents = coins_to_cents(price, ctx.world.places)
    anc = _anchor(ctx, item)
    lim = ctx.config.f("挂单价格偏离上限", 0.2)
    if anc and abs(price_cents - anc) / anc > lim and not params.get("system"):
        raise TownError("E1001", "偏离锚价超限")
    oid = ctx.world.state.nid("od")
    tax = ctx.config.f("市集税率", 0.08)
    if side == "sell":
        ctx.ledger.freeze(actor.agent_id, item, qty, oid)
    else:
        lock = int(qty * price_cents * (1 + tax))
        ctx.ledger.freeze(actor.agent_id, "coins", lock, oid)
    order = Order(
        order_id=oid, agent_id=actor.agent_id, item=item, qty=qty,
        price_cents=price_cents, side=side, created_tick=ctx.clock.tick,
        expire_day=ctx.clock.day + days, remaining=qty,
        system=bool(params.get("system")), caravan=bool(params.get("caravan")),
    )
    ctx.world.state.orders.append(order)
    return {"order_id": oid}


def _cancel(ctx, actor, params):
    require_not_frozen(actor)
    oid = params.get("order_id") or params.get("standing_order_id")
    if params.get("standing_order_id"):
        doc = ctx.world.state.documents.get(oid)
        if not doc or doc.payload.get("agent_id") != actor.agent_id:
            raise TownError("E1009")
        doc.status = "cancelled"
        ctx.ledger.unfreeze_doc(oid)
        return {"cancelled": oid}
    if ctx.world.state.matching:
        # 下一 tick 生效：标记
        for o in ctx.world.state.orders:
            if o.order_id == oid and o.agent_id == actor.agent_id:
                o.expire_day = ctx.clock.day  # 日结会清；简化为 tick 末仍可能成交
        # 按规格下一 tick：挂 pending_cancel
        ctx.world.state.plugin_data.setdefault("pending_cancel", set()).add(oid)
        return {"deferred": True}
    order = next((o for o in ctx.world.state.orders if o.order_id == oid), None)
    if not order or order.agent_id != actor.agent_id:
        raise TownError("E1009")
    ctx.ledger.unfreeze_doc(oid)
    ctx.world.state.orders = [o for o in ctx.world.state.orders if o.order_id != oid]
    return {"cancelled": oid}


def _match(ctx, world):
    pending = world.state.plugin_data.get("pending_cancel") or set()
    if pending:
        world.state.orders = [o for o in world.state.orders if o.order_id not in pending]
        for oid in pending:
            world.ledger.unfreeze_doc(oid)
        world.state.plugin_data["pending_cancel"] = set()
    tax = ctx.config.f("市集税率", 0.08)
    if any(e["name"] == "boom" for e in world.state.active_events):
        tax = tax / 2
    for item in ("food", "wood"):
        _match_item(ctx, world, item, tax)
    world.state.orders = [o for o in world.state.orders if o.remaining > 0]


def _match_item(ctx, world, item: str, tax: float) -> None:
    buys = sorted(
        [o for o in world.state.orders if o.side == "buy" and o.item == item and o.remaining > 0],
        key=lambda o: (-o.price_cents, o.created_tick, o.agent_id),
    )
    sells = sorted(
        [o for o in world.state.orders if o.side == "sell" and o.item == item and o.remaining > 0],
        key=lambda o: (o.price_cents, o.created_tick, o.agent_id),
    )
    _inject_standing(ctx, world, buys, sells, item)
    bi, si = 0, 0
    while bi < len(buys) and si < len(sells):
        b, s = buys[bi], sells[si]
        if b.price_cents < s.price_cents:
            break
        if b.created_tick <= s.created_tick:
            px = b.price_cents
        else:
            px = s.price_cents
        qty = min(b.remaining, s.remaining)
        tax_b = tax
        used = world.state.tax_free_used.get(b.agent_id, 0)
        notable_n = int(ctx.config.f("望族每日免税笔数", 5))
        buyer = world.state.agents.get(b.agent_id)
        if buyer and buyer.rank == "notable" and used < notable_n:
            tax_b = 0
            world.state.tax_free_used[b.agent_id] = used + 1
        pay = int(qty * px * (1 + tax_b))
        recv = int(qty * px)
        fee = pay - recv
        try:
            ctx.ledger.consume_frozen(b.order_id, b.agent_id, "coins", pay)
        except TownError:
            bi += 1
            continue
        extra_lock = sum(f.qty for f in world.state.freezes if f.document_id == b.order_id)
        if extra_lock and b.remaining - qty <= 0:
            ctx.ledger.unfreeze_doc(b.order_id)
        if s.system or s.caravan:
            ctx.ledger.credit(b.agent_id, s.item, qty)
            if not s.caravan:
                ctx.ledger.pool_credit(fee)
        else:
            ctx.ledger.consume_frozen(s.order_id, s.agent_id, s.item, qty)
            ctx.ledger.credit(s.agent_id, "coins", recv)
            ctx.ledger.credit(b.agent_id, s.item, qty)
            ctx.ledger.pool_credit(fee)
        b.remaining -= qty
        s.remaining -= qty
        world.state.day_trades.append({"item": s.item, "qty": qty, "price_cents": px})
        ctx.log.write(
            "TRADE_MATCH",
            params={"buy": b.order_id, "sell": s.order_id, "qty": qty, "price_cents": px, "item": s.item},
        )
        if b.remaining <= 0:
            ctx.ledger.unfreeze_doc(b.order_id)
            bi += 1
        if s.remaining <= 0:
            ctx.ledger.unfreeze_doc(s.order_id)
            si += 1


def _inject_standing(ctx, world, buys, sells, item: str) -> None:
    for d in world.state.documents.values():
        if d.kind != "standing" or d.status != "active":
            continue
        p = d.payload
        if p.get("item") != item:
            continue
        if p.get("type") == "limit_buy":
            price = p.get("price_cents")
            qty = p.get("qty", 1)
            sells_ok = any(o.side == "sell" and o.item == item and o.price_cents <= price for o in world.state.orders)
            if sells_ok:
                buys.append(Order(
                    order_id=d.document_id, agent_id=p["agent_id"], item=item, qty=qty,
                    price_cents=price, side="buy", created_tick=0, expire_day=9999, remaining=qty,
                ))
        elif p.get("type") == "limit_sell":
            price = p.get("price_cents")
            qty = p.get("qty", 1)
            buys_ok = any(o.side == "buy" and o.item == item and o.price_cents >= price for o in world.state.orders)
            if buys_ok:
                sells.append(Order(
                    order_id=d.document_id, agent_id=p["agent_id"], item=item, qty=qty,
                    price_cents=price, side="sell", created_tick=0, expire_day=9999, remaining=qty,
                ))
    buys.sort(key=lambda o: (-o.price_cents, o.created_tick, o.agent_id))
    sells.sort(key=lambda o: (o.price_cents, o.created_tick, o.agent_id))


def _restock(ctx, world):
    # 更新锚价
    by_item = {}
    for t in world.state.day_trades:
        by_item.setdefault(t["item"], []).append(t)
    keep = ctx.config.i("锚价空日保留", 1)
    for item in ("food", "wood"):
        trades = by_item.get(item) or []
        if trades:
            vol = sum(t["qty"] for t in trades)
            wavg = sum(t["qty"] * t["price_cents"] for t in trades) / vol
            world.state.anchors[item] = int(wavg)
        elif not keep:
            pass
    # 安定律复查
    lim = ctx.config.f("挂单价格偏离上限", 0.2)
    keep_o = []
    for o in world.state.orders:
        if o.system or o.caravan:
            keep_o.append(o)
            continue
        anc = world.state.anchors[o.item]
        if anc and abs(o.price_cents - anc) / anc > lim:
            ctx.ledger.unfreeze_doc(o.order_id)
            ctx.log.write("AGENT_ACTION", params={"action": "order_cancel", "reason": "safety"}, actor=o.agent_id)
        else:
            keep_o.append(o)
    world.state.orders = keep_o
    # 阿市补单
    for item, key in (("food", "阿市兜底卖单目标_食物"), ("wood", "阿市兜底卖单目标_木材")):
        target = ctx.config.i(key, 30)
        if any(e["name"] == "caravan" for e in world.state.active_events):
            target *= 2
        have = sum(o.remaining for o in world.state.orders if o.system and o.item == item and not o.caravan)
        need = target - have
        if need > 0:
            oid = world.state.nid("od")
            world.state.orders.append(Order(
                order_id=oid, agent_id="npc_market", item=item, qty=need,
                price_cents=world.state.anchors[item], side="sell",
                created_tick=world.state.tick, expire_day=world.state.day + 1,
                remaining=need, system=True,
            ))
    if any(e["name"] == "caravan" for e in world.state.active_events):
        prem = ctx.config.f("事件_行商溢价率", 1.3)
        for item, qkey in (("food", "事件_行商限量_食物"), ("wood", "事件_行商限量_木材")):
            q = ctx.config.i(qkey, 5)
            oid = world.state.nid("od")
            world.state.orders.append(Order(
                order_id=oid, agent_id="npc_trader", item=item, qty=q,
                price_cents=int(world.state.anchors[item] * prem), side="sell",
                created_tick=world.state.tick, expire_day=world.state.day + 1,
                remaining=q, system=True, caravan=True,
            ))


def _board(ctx, agent, pack):
    if pack["region"]["type"] != "market":
        return None
    return [
        {"id": o.order_id, "side": o.side, "item": o.item, "qty": o.remaining,
         "price": cents_to_coins(o.price_cents, ctx.world.places)}
        for o in ctx.world.state.orders if o.remaining > 0
    ]


def _summary(ctx, agent, pack):
    if pack["region"]["type"] != "town_hall":
        return None
    st = ctx.world.state
    return {
        "anchors": {k: cents_to_coins(v, ctx.world.places) for k, v in st.anchors.items()},
        "pool": cents_to_coins(st.public_pool_cents, ctx.world.places),
        "trades": len(st.day_trades),
    }
