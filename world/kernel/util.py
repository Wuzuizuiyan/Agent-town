from __future__ import annotations

import copy
from typing import Any

from world.kernel.errors import TownError
from world.kernel.mapgrid import bbox_tiles, region_at
from world.kernel.state import WorldState


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def manhattan(x0, y0, x1, y1) -> int:
    return abs(x1 - x0) + abs(y1 - y0)


def snapshot_state(state: WorldState) -> dict[str, Any]:
    return copy.deepcopy({
        "agents": state.agents,
        "freezes": state.freezes,
        "orders": state.orders,
        "buildings": state.buildings,
        "projects": state.projects,
        "documents": state.documents,
        "relations": state.relations,
        "inbox": state.inbox,
        "public_pool_cents": state.public_pool_cents,
        "bounties": state.bounties,
        "bulletins": state.bulletins,
        "blueprints": state.blueprints,
        "plebiscites": state.plebiscites,
        "election": state.election,
        "roads": state.roads,
        "open_farm": state.open_farm,
        "open_forest": state.open_forest,
        "plugin_data": state.plugin_data,
        "tax_free_used": state.tax_free_used,
        "npc_attitudes": state.npc_attitudes,
        "day_hours": {aid: dict(a.day_hours) for aid, a in state.agents.items()},
    })


def restore_state(state: WorldState, snap: dict[str, Any]) -> None:
    for k, v in snap.items():
        if k == "day_hours":
            continue
        setattr(state, k, v)
    for aid, hours in snap.get("day_hours", {}).items():
        if aid in state.agents:
            state.agents[aid].day_hours = hours


def require_not_frozen(agent) -> None:
    if agent.frozen:
        raise TownError("E1012")


def charge_time(agent, minutes: int) -> None:
    minutes = int(minutes)
    if minutes < 0:
        raise TownError("E1001")
    if agent.time_remaining < minutes:
        raise TownError("E1035")
    agent.time_remaining -= minutes


def require_region(agent, *apis: str) -> None:
    if region_at(agent.x, agent.y) not in apis:
        raise TownError("E1006")


def building_covers(b, x, y) -> bool:
    return (x, y) in bbox_tiles(b.x, b.y, b.w, b.h)


def season_of(day: int) -> str:
    r = (day - 1) % 7
    if r <= 1:
        return "harvest"
    if r <= 4:
        return "normal"
    return "drought"


def event_active(state: WorldState, name: str) -> bool:
    return any(e["name"] == name and e["days_left"] > 0 for e in state.active_events)


def prof_rank(hours: float, cfg) -> str:
    if hours >= cfg.f("熟练度_师傅晋级工时", 200):
        return "master"
    if hours >= cfg.f("熟练度_熟手晋级工时", 60):
        return "skilled"
    return "apprentice"


def prof_mul(rank: str, cfg) -> float:
    if rank == "master":
        return 1.0 + cfg.f("熟练度_师傅加成", 0.3)
    if rank == "skilled":
        return 1.0 + cfg.f("熟练度_熟手加成", 0.15)
    return 1.0


def mood_mul(mood: float, cfg) -> float:
    if mood >= cfg.f("心情高效阈值", 70):
        return 1.0 + cfg.f("心情高效产出加成", 0.2)
    if mood <= cfg.f("心情低效阈值", 35):
        return 1.0 - cfg.f("心情低效产出折减", 0.2)
    return 1.0


def rank_of(score: float, cfg) -> str:
    base = cfg.f("声誉基础分", 50)
    good = cfg.f("声望等级_良民门槛", 65)
    notable = cfg.f("声望等级_望族门槛", 78)
    elder = cfg.f("声望等级_乡贤门槛", 90)
    if score >= elder:
        return "elder"
    if score >= notable:
        return "notable"
    if score >= good:
        return "good_neighbor"
    if score >= base:
        return "resident"
    return "newcomer"
