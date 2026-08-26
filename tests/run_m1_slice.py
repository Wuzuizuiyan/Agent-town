#!/usr/bin/env python3
"""M1 竖切：24 tick 农夫存活 + 市集成交抽税。日志写入 /opt/cursor/artifacts。"""

from __future__ import annotations

import json
from pathlib import Path

from world.kernel.money import coins_to_cents, cents_to_coins
from world.kernel.world import TownWorld


def enroll(world: TownWorld, name="张三", x=8, y=15, **extra):
    owner = world.register_owner()
    info = world.register_agent(owner["owner_id"], {
        "name": name,
        "traits_words": ["稳重", "肯干", "老实"],
        "vocation": "农夫",
        "backstory": "来讨生活",
        "intro_npc": "npc_herald",
    })
    agent = world.state.agents[info["agent_id"]]
    agent.x, agent.y = x, y
    for k, v in extra.items():
        setattr(agent, k, v)
    return {**owner, **info, "agent": agent}

OUT = Path("/opt/cursor/artifacts/m1_vertical_slice.json")


def main() -> None:
    w = TownWorld(profile="first_gun")
    farmer = enroll(w, name="农夫甲", x=8, y=15, food=8)
    seller = enroll(w, name="卖家甲", x=47, y=35, food=6)
    buyer = enroll(w, name="买家乙", x=47, y=35, food=0)
    buyer["agent"].coins_cents = coins_to_cents(30, w.places)
    pool0 = w.state.public_pool_cents
    traded = False
    for i in range(24):
        w.begin_tick()
        fa = farmer["agent"]
        seq = 1
        if fa.satiety < 55 and fa.food > 0:
            w.submit_action(farmer["agent_id"], w.state.tick, seq, "eat", {"qty": 1})
            seq += 1
        if fa.time_remaining >= 60:
            w.submit_action(farmer["agent_id"], w.state.tick, seq, "work", {})
        if i == 0:
            w.submit_action(seller["agent_id"], w.state.tick, 1, "order_place", {
                "item": "food", "qty": 2, "price": 2, "side": "sell", "days": 2,
            })
            w.submit_action(buyer["agent_id"], w.state.tick, 1, "order_place", {
                "item": "food", "qty": 2, "price": 2, "side": "buy", "days": 2,
            })
        w.end_tick()
        if any(ev.type == "TRADE_MATCH" for ev in w.state.events):
            traded = True
    w.step(1)
    payload = {
        "tick": w.state.tick,
        "day": w.state.day,
        "farmer": {
            "satiety": farmer["agent"].satiety,
            "food": farmer["agent"].food,
            "frozen": farmer["agent"].frozen,
            "farm_hours": farmer["agent"].farmer_hours,
            "coins": cents_to_coins(farmer["agent"].coins_cents, w.places),
        },
        "market": {
            "traded": traded,
            "buyer_food": buyer["agent"].food,
            "pool0": cents_to_coins(pool0, w.places),
            "pool": cents_to_coins(w.state.public_pool_cents, w.places),
            "matches": sum(1 for ev in w.state.events if ev.type == "TRADE_MATCH"),
        },
        "plugins": list(w.profile),
        "ok": (
            farmer["agent"].satiety > 0
            and not farmer["agent"].frozen
            and traded
            and w.state.public_pool_cents > pool0
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
