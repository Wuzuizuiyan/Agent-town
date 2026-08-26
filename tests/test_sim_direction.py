"""与 sim 对照方向：躺平挨饿、公共池不破零。"""

from world.kernel.world import TownWorld

from tests.conftest import enroll


def test_idle_starves_and_may_freeze():
    w = TownWorld(profile=["survival"])
    info = enroll(w, food=0)
    agent = info["agent"]
    w.step(50)
    assert agent.satiety < 20
    assert agent.idle_ticks >= 48
    assert agent.frozen


def test_pool_never_negative_on_odd_jobs():
    w = TownWorld(profile=["survival"])
    w.state.public_pool_cents = 50
    info = enroll(w, name="杂役甲", x=31, y=31)
    for _ in range(12):
        w.begin_tick()
        w.submit_action(info["agent_id"], w.state.tick, 1, "work", {})
        w.end_tick()
    w.step(13)
    assert w.state.public_pool_cents >= 0
