from world.kernel.errors import TownError
from world.kernel.money import coins_to_cents
from world.kernel.world import TownWorld

from tests.conftest import enroll


def test_time_budget_e1035():
    w = TownWorld(profile=["survival"])
    info = enroll(w, x=8, y=15)
    w.begin_tick()
    w.submit_action(info["agent_id"], w.state.tick, 1, "work", {})
    try:
        w.submit_action(info["agent_id"], w.state.tick, 2, "work", {})
        assert False
    except TownError as e:
        assert e.code == "E1035"
    w.end_tick()


def test_freeze_e1008_vs_e1023():
    w = TownWorld(profile="first_gun")
    info = enroll(w, x=47, y=35, food=1)
    agent = info["agent"]
    agent.coins_cents = coins_to_cents(10, w.places)
    w.ledger.freeze(agent.agent_id, "food", 1, "doc_lock")
    w.begin_tick()
    try:
        w.submit_action(agent.agent_id, w.state.tick, 1, "order_place", {
            "item": "food", "qty": 1, "price": 2, "side": "sell", "days": 1,
        })
        assert False
    except TownError as e:
        assert e.code == "E1023"
    try:
        w.ledger.debit(agent.agent_id, "wood", 1)
        assert False
    except TownError as e:
        assert e.code == "E1008"
    w.end_tick()


def test_idempotent_replay():
    w = TownWorld(profile=["survival"])
    info = enroll(w, x=8, y=15, food=5)
    w.begin_tick()
    a = w.submit_action(info["agent_id"], w.state.tick, 1, "eat", {"qty": 1})
    b = w.submit_action(info["agent_id"], w.state.tick, 1, "eat", {"qty": 1})
    assert a["accepted"] and b["idempotent"] is True
    assert info["agent"].food == 4
    w.end_tick()


def test_farmer_survives_24_ticks():
    w = TownWorld(profile="first_gun")
    info = enroll(w, x=8, y=15, food=8)
    aid = info["agent_id"]
    agent = info["agent"]
    for i in range(24):
        w.begin_tick()
        if agent.satiety < 50 and agent.food > 0 and agent.time_remaining >= 10:
            w.submit_action(aid, w.state.tick, 1, "eat", {"qty": 1})
            seq = 2
        else:
            seq = 1
        if agent.time_remaining >= 60:
            w.submit_action(aid, w.state.tick, seq, "work", {})
        w.end_tick()
    assert agent.satiety > 0
    assert not agent.frozen
    assert agent.day_hours.get("farm", 0) > 0


def test_day_settle_pays_food_and_mint():
    w = TownWorld(profile=["survival"])
    info = enroll(w, x=8, y=15, food=8)
    aid = info["agent_id"]
    agent = info["agent"]
    for _ in range(24):
        w.begin_tick()
        w.submit_action(aid, w.state.tick, 1, "work", {})
        w.end_tick()
    food_before = agent.food
    coins_before = agent.coins_cents
    w.step(1)  # tick 25 = 日结
    assert agent.food > food_before
    assert agent.coins_cents > coins_before
    mint_ev = [ev for ev in w.state.events if ev.type == "MINT"]
    assert mint_ev
    assert all(ev.day == 1 for ev in mint_ev)
    assert w.state.stats.get("mint_cents", 0) > 0


def test_market_match_and_tax():
    w = TownWorld(profile="first_gun")
    seller = enroll(w, name="卖家甲", x=47, y=35, food=5)
    buyer = enroll(w, name="买家乙", x=47, y=35, food=0)
    buyer["agent"].coins_cents = coins_to_cents(20, w.places)
    pool0 = w.state.public_pool_cents
    w.begin_tick()
    w.submit_action(seller["agent_id"], w.state.tick, 1, "order_place", {
        "item": "food", "qty": 1, "price": 2, "side": "sell", "days": 1,
    })
    w.submit_action(buyer["agent_id"], w.state.tick, 1, "order_place", {
        "item": "food", "qty": 1, "price": 2, "side": "buy", "days": 1,
    })
    w.end_tick()
    assert any(ev.type == "TRADE_MATCH" for ev in w.state.events)
    assert buyer["agent"].food >= 1
    assert w.state.public_pool_cents > pool0


def test_bind_and_warehouse():
    from world.kernel.state import Building
    w = TownWorld(profile=["survival", "construction"])
    info = enroll(w, name="仓管甲", x=31, y=31, food=10)
    bid = "bd_wh"
    w.state.buildings[bid] = Building(
        building_id=bid, kind="仓库", venue_kind="warehouse", effect_kind="warehouse",
        x=47, y=35, w=2, h=2, status="done",
    )
    w.begin_tick()
    bound = w.submit_action(info["agent_id"], w.state.tick, 1, "bind", {
        "kind": "warehouse", "building_id": bid,
    })
    assert bound["accepted"]
    w.end_tick()
    info["agent"].x, info["agent"].y = 47, 35
    w.begin_tick()
    stored = w.submit_action(info["agent_id"], w.state.tick, 1, "warehouse", {
        "op": "deposit", "item": "food", "qty": 3,
    })
    assert stored["accepted"]
    assert info["agent"].food == 7
    assert info["agent"].receipt_food == 3
    w.end_tick()


def test_talk_and_bounty_plugin_isolation():
    w = TownWorld(profile="full")
    a = enroll(w, name="社交甲", x=31, y=31)
    b = enroll(w, name="社交乙", x=31, y=31)
    w.begin_tick()
    out = w.submit_action(a["agent_id"], w.state.tick, 1, "talk", {
        "peer_id": b["agent_id"], "content": "今日田里怎样",
    })
    assert out["accepted"]
    w.end_tick()
    w.reload_plugins([p for p in w.profile if p != "bounty"])
    assert w.bus.action_handler("bounty_post") is None
    assert w.bus.action_handler("work") is not None


def test_rejected_action_keeps_agent_identity():
    w = TownWorld(profile=["survival"])
    info = enroll(w, x=8, y=15, food=5)
    agent = info["agent"]
    w.begin_tick()
    try:
        w.submit_action(info["agent_id"], w.state.tick, 1, "eat", {"qty": 0})
        assert False
    except TownError as e:
        assert e.code == "E1001"
    assert agent is w.state.agents[info["agent_id"]]
    energy_at_reject = agent.energy
    w.end_tick()
    w.begin_tick()
    assert agent is w.state.agents[info["agent_id"]]
    assert agent.energy < energy_at_reject
    w.end_tick()


def test_sleep_restores_energy_this_tick():
    w = TownWorld(profile=["survival"])
    info = enroll(w, x=23, y=51)
    agent = info["agent"]
    w.step(5)
    w.begin_tick()
    energy_after_decay = agent.energy
    out = w.submit_action(info["agent_id"], w.state.tick, 1, "sleep", {})
    assert out["accepted"]
    # 清醒衰减已在第 1 步扣过；睡眠 tick 应改为 +8（无住宅加成）
    assert agent.energy == energy_after_decay + 2 + 8
    w.end_tick()
    w.begin_tick()
    assert agent.energy == energy_after_decay + 8
    w.end_tick()
