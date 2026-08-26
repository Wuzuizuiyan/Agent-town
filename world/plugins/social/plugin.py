"""对话、关系值、酒馆心情乘算。"""

from __future__ import annotations

from world.kernel.errors import TownError
from world.kernel.mapgrid import region_at
from world.kernel.util import require_not_frozen

PLUGIN_ID = "social"
INJECT = ["clock", "map", "agents", "needs", "log", "config", "world", "llm"]


def apply(ctx):
    ctx.actions.register("talk", lambda a, p: _talk(ctx, a, p))
    ctx.effects.register("talk_mood_mul", lambda *_: None)
    ctx.hooks.daily_after(6, lambda world: _decay_rel(ctx, world))
    ctx.events.allow("DIALOGUE")


def _talk(ctx, actor, params):
    require_not_frozen(actor)
    peer_id = params.get("peer_id")
    content = params.get("content") or ""
    if not peer_id or len(content) > 200:
        raise TownError("E1001")
    cap = ctx.config.i("对话频率上限", 3)
    if actor.talks_this_tick >= cap:
        raise TownError("E1011")
    peer = ctx.world.state.agents.get(peer_id)
    if not peer:
        raise TownError("E1010")
    if peer.frozen:
        raise TownError("E1010")
    if region_at(actor.x, actor.y) != region_at(peer.x, peer.y):
        raise TownError("E1010")
    # NPC 限额
    reply = None
    if peer.kind == "npc":
        reply = _npc_talk(ctx, actor, peer, content)
    actor.talks_this_tick += 1
    gain = ctx.config.f("对话心情收益", 2)
    venue = ctx.map.venue_at(actor.x, actor.y)
    if venue and venue.get("kind") == "tavern":
        gain *= 2
    gain *= ctx.config.trait_mul(actor.trait, "对话心情收益") or 1.0
    gain *= ctx.config.trait_mul(actor.trait, "心情正向收益") or 1.0
    actor.mood += gain
    ctx.needs.clamp(actor.agent_id)
    rel = ctx.agents.relation(actor.agent_id, peer.agent_id)
    cap_g = ctx.config.f("关系值_同对象日上限", 6)
    add = ctx.config.f("关系值_对话", 1)
    if rel.gain_today + add <= cap_g:
        rel.value = min(ctx.config.f("关系值上限", 100), rel.value + add)
        rel.gain_today += add
    rel.interact_count += 1
    rel.last_tick = ctx.clock.tick
    inbox = ctx.world.state.inbox
    inbox.setdefault(actor.agent_id, _empty_inbox())
    inbox.setdefault(peer.agent_id, _empty_inbox())
    inbox[peer.agent_id]["unread_dialogues"].append(
        {"from": actor.agent_id, "content": content, "tick": ctx.clock.tick}
    )
    if reply:
        inbox[actor.agent_id]["unread_dialogues"].append(
            {"from": peer.agent_id, "content": reply, "tick": ctx.clock.tick}
        )
    ctx.log.write("DIALOGUE", actor=actor.agent_id, params={"peer": peer_id, "content": content, "reply": reply})
    return {"reply": reply}


def _npc_talk(ctx, actor, peer, content):
    data = ctx.world.state.plugin_data.setdefault("npc_talks", {})
    key_p = (actor.agent_id, peer.npc_id, ctx.clock.day)
    key_t = (peer.npc_id, ctx.clock.day)
    data[key_p] = data.get(key_p, 0) + 1
    data[key_t] = data.get(key_t, 0) + 1
    if data[key_p] > ctx.config.i("NPC日对话上限_单人", 3) or data[key_t] > ctx.config.i("NPC日对话上限_总额", 12):
        raise TownError("E1043")
    att = ctx.world.state.npc_attitudes.get((peer.npc_id, actor.agent_id), 50)
    warm = ctx.config.f("态度_热络阈值", 65)
    cold = ctx.config.f("态度_冷淡阈值", 35)
    if att >= warm:
        rank = 2
    elif att <= cold:
        rank = 0
    else:
        rank = 1
    if actor.loan_ban_until >= ctx.clock.day:
        rank = max(0, rank - 1)
    band = ("cold", "normal", "warm")[rank]
    return ctx.llm.complete_text({
        "attitude": band, "npc_id": peer.npc_id, "name": peer.name,
        "traits": " ".join(peer.trait_words), "topic": content[:20],
    })


def _empty_inbox():
    return {"unread_dialogues": [], "trade_notices": [], "pledge_notices": [], "intel_shares": [], "gm_facts": []}


def _decay_rel(ctx, world):
    step = ctx.config.f("关系值日衰减", 1)
    lo, hi = ctx.config.f("关系值下限", -50), ctx.config.f("关系值上限", 100)
    for rel in world.state.relations.values():
        a = world.state.agents.get(rel.a)
        b = world.state.agents.get(rel.b)
        if a and b and (a.frozen or b.frozen):
            rel.gain_today = 0
            rel.loss_today = 0
            continue
        if rel.value > 0:
            rel.value = max(0, rel.value - step)
        elif rel.value < 0:
            rel.value = min(0, rel.value + step)
        rel.value = max(lo, min(hi, rel.value))
        rel.gain_today = 0
        rel.loss_today = 0
