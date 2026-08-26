from world.kernel.bus import PluginBus
from world.kernel.errors import TownError
from world.kernel.world import TownWorld


def test_unload_rolls_back_actions():
    w = TownWorld(profile=["survival"])
    assert w.bus.action_handler("work") is not None
    w.bus.unload("survival")
    assert w.bus.action_handler("work") is None
    w.begin_tick()
    owner = w.register_owner()
    info = w.register_agent(owner["owner_id"], {
        "name": "李四", "traits_words": ["甲", "乙", "丙"],
        "vocation": "农夫", "backstory": "", "intro_npc": "npc_herald",
    })
    try:
        w.submit_action(info["agent_id"], w.state.tick, 1, "work", {})
        assert False, "should reject"
    except TownError as e:
        assert e.code == "E1001"


def test_missing_inject_skips_plugin():
    bus = PluginBus({"clock": object()})

    def apply(ctx):
        raise AssertionError("should not apply")

    bus.load("x", ["clock", "missing"], apply)
    assert not bus.has("x")


def test_hook_order():
    bus = PluginBus({"clock": 1})
    seq = []

    def apply_a(ctx):
        ctx.hooks.daily_after(1, lambda *_: seq.append("a"))

    def apply_b(ctx):
        ctx.hooks.daily_after(1, lambda *_: seq.append("b"))

    bus.load("a", ["clock"], apply_a)
    bus.load("b", ["clock"], apply_b)
    bus.run_hooks("daily", 1)
    assert seq == ["a", "b"]
    bus.unload("a")
    seq.clear()
    bus.run_hooks("daily", 1)
    assert seq == ["b"]
