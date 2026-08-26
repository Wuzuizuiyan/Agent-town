from world.kernel.errors import TownError
from world.kernel.world import TownWorld

from tests.conftest import enroll


def test_unload_market_keeps_labor_and_eat():
    w = TownWorld(profile="first_gun")
    info = enroll(w, x=8, y=15, food=10)
    aid = info["agent_id"]
    w.begin_tick()
    w.submit_action(aid, w.state.tick, 1, "work", {})
    w.end_tick()

    w.reload_plugins(["survival"])
    assert w.bus.action_handler("order_place") is None
    assert w.bus.action_handler("work") is not None

    w.begin_tick()
    out = w.submit_action(aid, w.state.tick, 1, "work", {})
    assert out["accepted"]
    w.end_tick()

    w.begin_tick()
    eat = w.submit_action(aid, w.state.tick, 1, "eat", {"qty": 1})
    assert eat["accepted"]
    try:
        w.submit_action(aid, w.state.tick, 2, "order_place", {
            "item": "food", "qty": 1, "price": 2, "side": "sell", "days": 1,
        })
        assert False, "order_place should be unknown"
    except TownError as e:
        assert e.code == "E1001"
    w.end_tick()

    w.reload_plugins(["survival", "market"])
    agent = w.state.agents[aid]
    agent.x, agent.y = 47, 35
    w.begin_tick()
    placed = w.submit_action(aid, w.state.tick, 1, "order_place", {
        "item": "food", "qty": 1, "price": 2, "side": "sell", "days": 1,
    })
    assert placed["accepted"]
    w.end_tick()


def test_pause_rejects_actions():
    w = TownWorld(profile=["survival"])
    info = enroll(w)
    w.set_paused(True)
    try:
        w.begin_tick()
        assert False
    except TownError as e:
        assert e.code == "E1014"
    w.state.in_tick = True
    w.state.paused = True
    try:
        w.submit_action(info["agent_id"], w.state.tick, 1, "eat", {"qty": 1})
        assert False
    except TownError as e:
        assert e.code == "E1014"
