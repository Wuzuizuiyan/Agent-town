"""季节播报辅助与随机事件判定。"""

from __future__ import annotations

from world.kernel.state import Agent
from world.kernel.util import season_of

PLUGIN_ID = "events"
INJECT = ["clock", "log", "config", "world", "rng", "agents"]

CATALOG = (
    ("boom", "市集繁荣", "事件_市集繁荣概率", 1),
    ("storm", "暴风雨", "事件_暴风雨概率", 1),
    ("pest", "虫灾", "事件_虫灾概率", 2),
    ("caravan", "商队到访", "事件_商队到访概率", 1),
)


def apply(ctx):
    ctx.hooks.daily_after(1, lambda world: _daily(ctx, world))
    ctx.events.allow("WORLD_EVENT")


def _hit(ctx, day: int, name: str, prob: float) -> bool:
    rng = ctx.rng.stream("events", name, str(day))
    return rng.random() < prob


def _plan(ctx, day: int, active: list[dict]) -> list[dict]:
    if ctx.config.i("随机事件开关", 1) != 1:
        return []
    cap = ctx.config.i("同时最大事件数", 1)
    living = [e for e in active if e.get("days_left", 0) > 0]
    out = []
    if len(living) >= cap:
        return out
    for name, label, key, dur in CATALOG:
        if any(e["name"] == name for e in living):
            continue
        if _hit(ctx, day, name, ctx.config.f(key, 0)):
            out.append({"name": name, "label": label, "days_left": dur, "days": dur})
            living.append(out[-1])
            if len(living) >= cap:
                break
    return out


def _daily(ctx, world):
    day = world.state.day
    kept = []
    for ev in world.state.active_events:
        ev = dict(ev)
        ev["days_left"] = int(ev.get("days_left", 1)) - 1
        if ev["days_left"] <= 0:
            ctx.log.write("WORLD_EVENT", params={"name": ev["name"], "op": "end"})
            if ev["name"] == "caravan":
                _despawn_trader(world)
        else:
            kept.append(ev)
    world.state.active_events = kept
    started = _plan(ctx, day, world.state.active_events)
    for ev in started:
        world.state.active_events.append(ev)
        ctx.log.write("WORLD_EVENT", params={"name": ev["name"], "op": "start", "days": ev["days"]})
        if ev["name"] == "caravan":
            _spawn_trader(ctx, world)
    disaster = any(e["name"] in ("storm", "pest") for e in world.state.active_events)
    if disaster:
        drain = ctx.config.f("灾害心情日减益", 3)
        for a in world.agents.settlers():
            a.mood -= drain
            world.needs.clamp(a.agent_id)
    tomorrow = day + 1
    sim = [dict(e) for e in world.state.active_events]
    for e in sim:
        e["days_left"] = int(e.get("days_left", 1)) - 1
    sim = [e for e in sim if e["days_left"] > 0]
    world.state.event_forecast = _plan(ctx, tomorrow, sim)


def _spawn_trader(ctx, world):
    if "npc_trader" in world.state.agents:
        return
    row = ctx.config.npc_by_id_or_name("npc_trader")
    if not row:
        return
    ag = Agent(
        agent_id="npc_trader", owner_id="system", name=row.get("NPC名") or "老商",
        token="npc", trait=None, trait_words=(row.get("性格三词") or "").split(),
        vocation=row.get("职能") or "", backstory="", intro_npc="",
        x=47, y=35, kind="npc", npc_id="npc_trader", region_home="market",
    )
    world.state.agents["npc_trader"] = ag
    ctx.log.write("WORLD_EVENT", params={"npc": "npc_trader", "op": "arrive"})


def _despawn_trader(world):
    world.state.agents.pop("npc_trader", None)
    world.state.orders = [o for o in world.state.orders if not o.caravan]
