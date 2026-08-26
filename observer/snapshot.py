"""公开观测快照。"""

from __future__ import annotations

from observer.appearance import DEFAULT_APPEARANCE
from observer.labels import NPC_STANCE, label_of
from world.kernel.mapgrid import REGIONS, region_at
from world.kernel.state import Agent, WorldState


def tile_code(state: WorldState, x: int, y: int) -> str:
    for b in state.buildings.values():
        if b.venue_kind == "well" and b.status == "done" and b.x <= x < b.x + b.w and b.y <= y < b.y + b.h:
            return "o"
    if (x, y) in state.roads:
        return "R"
    region = region_at(x, y)
    if region == "well":
        return "w"
    if region == "town_hall":
        return "H"
    if region == "farm":
        return "f" if (x, y) in state.open_farm else "F"
    if region == "forest":
        return "t" if (x, y) in state.open_forest else "T"
    if region == "market":
        return "m"
    if region == "residential":
        return "r"
    return "."


def build_tile_string(state: WorldState) -> str:
    chars = []
    for y in range(64):
        for x in range(64):
            chars.append(tile_code(state, x, y))
    return "".join(chars)


def person_payload(agent: Agent) -> dict:
    appearance = dict(agent.appearance or DEFAULT_APPEARANCE)
    action = agent.activity_action or ("frozen" if agent.frozen else "idle")
    label = agent.activity_label or label_of(action)
    payload = {
        "id": agent.npc_id or agent.agent_id,
        "kind": agent.kind,
        "name": agent.name,
        "vocation": agent.vocation,
        "appearance": appearance,
        "position": {"x": agent.x, "y": agent.y, "region": region_at(agent.x, agent.y)},
        "facing": agent.facing or "s",
        "activity": {
            "action": action,
            "label": label,
            "started_tick": agent.activity_tick,
        },
        "frozen": bool(agent.frozen),
    }
    if agent.kind == "npc":
        payload["npc_id"] = agent.npc_id
        payload["role"] = agent.vocation
    return payload


def _public_headlines(gazette: dict) -> list[str]:
    out = []
    for h in gazette.get("headlines") or []:
        s = str(h)
        if s.startswith("WORLD_EVENT"):
            if "pest" in s:
                out.append("虫灾")
            elif "storm" in s:
                out.append("暴风雨")
            elif "boom" in s:
                out.append("市集繁荣")
            elif "caravan" in s:
                out.append("商队到访")
            else:
                out.append("世界事件")
        elif s.startswith("BOUNTY"):
            out.append("悬赏动态")
        elif s.startswith("LAW"):
            out.append("镇规执法")
        else:
            out.append(s)
    return out


def build_snapshot(world) -> dict:
    state: WorldState = world.state
    venues = []
    for b in state.buildings.values():
        venues.append({
            "building_id": b.building_id,
            "kind": b.venue_kind,
            "x": b.x, "y": b.y, "w": b.w, "h": b.h,
            "status": b.status,
        })
    for p in state.projects.values():
        if p.status in ("pledging", "building"):
            venues.append({
                "building_id": None,
                "kind": p.venue_kind,
                "x": p.x, "y": p.y, "w": p.w, "h": p.h,
                "status": p.status,
                "project_id": p.project_id,
            })
    people = [person_payload(a) for a in state.agents.values()]
    people.sort(key=lambda p: (p["kind"] != "npc", p["id"]))
    gazette = dict(state.gazette or {})
    gazette["headlines"] = _public_headlines(gazette)
    gazette.setdefault("population", len(world.agents.settlers()))
    gazette.setdefault("pool", 0)
    return {
        "tick": state.tick,
        "day": state.day,
        "clock": {"hour": state.hour, "speed": state.speed, "paused": state.paused},
        "map": {
            "width": 64,
            "height": 64,
            "tiles": build_tile_string(state),
            "venues": venues,
            "regions": {name: {"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3]} for name, b in REGIONS.items()},
        },
        "people": people,
        "gazette": gazette,
        "population": {
            "settlers": len(world.agents.settlers()),
            "npcs": len(world.agents.npcs()),
        },
    }


def apply_npc_stance(agent: Agent) -> None:
    if agent.kind != "npc" or agent.frozen:
        return
    if agent.activity_action and agent.activity_action not in ("idle",):
        return
    action, label = NPC_STANCE.get(agent.npc_id or "", ("idle", "值守"))
    agent.activity_action = action
    agent.activity_label = label
