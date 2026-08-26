"""NPC 态度快照、闲谈。对话生成在 social；竞选投票在 governance。"""

from __future__ import annotations

from world.kernel.util import season_of

PLUGIN_ID = "npc"
INJECT = ["clock", "agents", "log", "config", "world", "llm", "rng"]


def apply(ctx):
    ctx.hooks.daily_after(6, lambda world: _snapshot(ctx, world))
    ctx.hooks.daily_after(9, lambda world: _gossip(ctx, world))
    for npc in ctx.world.agents.npcs():
        if npc.npc_id:
            ctx.npc.register(npc.npc_id, lambda *_a, **_k: None)


def _snapshot(ctx, world):
    w_rep = ctx.config.f("态度_声誉权重", 0.5)
    w_rel = ctx.config.f("态度_关系权重", 0.5)
    for npc in world.agents.npcs():
        if not npc.npc_id:
            continue
        for settler in world.agents.settlers():
            rel = world.agents.relation(npc.agent_id, settler.agent_id)
            rel_norm = (rel.value + 50) / 150 * 100
            att = w_rep * settler.reputation + w_rel * rel_norm
            world.state.npc_attitudes[(npc.npc_id, settler.agent_id)] = max(0.0, min(100.0, att))


def _gossip(ctx, world):
    if ctx.config.i("老册闲谈开关", 1) != 1:
        return
    cap = ctx.config.i("老册闲谈日上限", 1)
    if cap < 1:
        return
    gazette = world.state.gazette or {}
    headlines = gazette.get("headlines") or []
    if not headlines:
        season = season_of(world.state.day)
        headlines = [f"今日季节 {season}"]
    topic = headlines[0]
    text = ctx.llm.complete_text({
        "attitude": "normal",
        "npc_id": "npc_herald",
        "name": "老册",
        "traits": "健谈 缜密 守旧",
        "topic": str(topic)[:40],
    })
    payload = {
        "day": world.state.day,
        "tick": world.state.tick,
        "actor": "npc_herald",
        "content": text,
        "system": True,
    }
    world.state.bulletins.append(payload)
    has_board = any(b.venue_kind == "bulletin" and b.status == "done" for b in world.state.buildings.values())
    if not has_board:
        for a in world.agents.settlers():
            box = world.state.inbox.setdefault(a.agent_id, {
                "unread_dialogues": [], "trade_notices": [], "pledge_notices": [],
                "intel_shares": [], "gm_facts": [],
            })
            box.setdefault("gm_facts", []).append({"from": "npc_herald", "content": text, "tick": world.state.tick})
    ctx.log.write("BULLETIN", actor="npc_herald", params={"gossip": True, "content": text})
