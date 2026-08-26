"""演示人口：脚本定居者 + NPC 区域内缓步。不改经济规则。"""

from __future__ import annotations

import os

from observer.appearance import AppearanceError, validate_appearance
from observer.labels import NPC_STANCE
from observer.snapshot import apply_npc_stance
from world.kernel.errors import TownError
from world.kernel.mapgrid import REGIONS, region_at
from world.kernel.world import TownWorld

DEMO_CAST = [
    {
        "name": "禾苗",
        "vocation": "农夫",
        "traits_words": ["肯干", "早起", "恋田"],
        "intro_npc": "npc_farmer",
        "appearance": {
            "skin": "warm_1", "hair_style": "short_bangs", "hair_color": "brown",
            "eyes": "round", "top": "work_shirt", "bottom": "trousers", "accessory": "hat",
        },
        "home": (18, 48),
        "job": (12, 15),
        "role": "farm",
    },
    {
        "name": "木秋",
        "vocation": "樵夫",
        "traits_words": ["沉默", "有劲", "恋山"],
        "intro_npc": "npc_woodcutter",
        "appearance": {
            "skin": "tan", "hair_style": "messy", "hair_color": "ink",
            "eyes": "narrow", "top": "tunic", "bottom": "shorts", "accessory": "none",
        },
        "home": (28, 52),
        "job": (40, 15),
        "role": "wood",
    },
    {
        "name": "市川",
        "vocation": "贩子",
        "traits_words": ["精明", "健谈", "算账"],
        "intro_npc": "npc_market",
        "appearance": {
            "skin": "pale", "hair_style": "bob", "hair_color": "gold",
            "eyes": "bright", "top": "vest", "bottom": "skirt", "accessory": "scarf",
        },
        "home": (22, 55),
        "job": (47, 35),
        "role": "market",
    },
    {
        "name": "眠霜",
        "vocation": "闲人",
        "traits_words": ["贪睡", "怕冷", "软和"],
        "intro_npc": "npc_herald",
        "appearance": {
            "skin": "pale", "hair_style": "long", "hair_color": "silver",
            "eyes": "round", "top": "robe", "bottom": "wrap", "accessory": "flower",
        },
        "home": (14, 50),
        "job": (14, 50),
        "role": "sleep",
    },
    {
        "name": "谈竹",
        "vocation": "说书",
        "traits_words": ["话多", "热心", "记事"],
        "intro_npc": "npc_herald",
        "appearance": {
            "skin": "warm_2", "hair_style": "bun", "hair_color": "auburn",
            "eyes": "bright", "top": "coat", "bottom": "trousers", "accessory": "glasses",
        },
        "home": (30, 46),
        "job": (31, 31),
        "role": "talk",
    },
    {
        "name": "行路",
        "vocation": "信使",
        "traits_words": ["脚快", "耐走", "好奇"],
        "intro_npc": "npc_guard",
        "appearance": {
            "skin": "deep", "hair_style": "short", "hair_color": "ink",
            "eyes": "narrow", "top": "coat", "bottom": "trousers", "accessory": "scarf",
        },
        "home": (23, 51),
        "job": (31, 31),
        "role": "courier",
        "waypoints": [(12, 15), (31, 31), (47, 35), (23, 51), (40, 15)],
    },
]


def _catalog(world: TownWorld):
    return world.cfg.appearance


def seed_demo(world: TownWorld) -> list[str]:
    """幂等：已有 demo_seeded 则跳过。每名演示定居者单独主人。"""
    if world.state.plugin_data.get("demo_seeded"):
        return list(world.state.plugin_data.get("demo_ids") or [])
    ids = []
    for spec in DEMO_CAST:
        owner = world.register_owner()
        card = {
            "name": spec["name"],
            "traits_words": spec["traits_words"],
            "vocation": spec["vocation"],
            "backstory": "观测演示居民",
            "intro_npc": spec["intro_npc"],
            "appearance": spec["appearance"],
        }
        info = world.register_agent(owner["owner_id"], card)
        agent = world.state.agents[info["agent_id"]]
        hx, hy = spec["home"]
        agent.x, agent.y = hx, hy
        agent.food = 24
        agent.energy = 100
        agent.satiety = 90
        agent.demo = True
        agent.plugin_meta = {"role": spec["role"], "job": spec["job"], "home": spec["home"],
                             "waypoints": spec.get("waypoints") or [], "wp": 0}
        if spec["role"] == "sleep":
            agent.frozen = True
            agent.activity_action = "frozen"
            agent.activity_label = "离线睡眠"
        ids.append(info["agent_id"])
    world.state.plugin_data["demo_seeded"] = True
    world.state.plugin_data["demo_ids"] = ids
    world.observer_demo = True
    speed = float(os.environ.get("TOWN_DEMO_SPEED") or 900)
    world.state.speed = speed
    world.state.gazette = world.state.gazette or {
        "day": 0,
        "headlines": ["拓居点刚开镇，观察者可在地图上看小人。"],
        "chronicle": ["演示居民已入驻"],
        "population": len(ids),
        "pool": 0,
        "season_today": "spring",
    }
    return ids


def join_demo(world: TownWorld, body: dict) -> dict:
    if not getattr(world, "observer_demo", False) and not world.state.plugin_data.get("demo_seeded"):
        raise TownError("E1014", "未开启演示模式")
    name = (body.get("name") or "过客").strip()[:12] or "过客"
    vocation = (body.get("vocation") or "旅人").strip()[:8] or "旅人"
    words = body.get("traits_words") or ["观", "察", "者"]
    try:
        appearance = validate_appearance(body.get("appearance"), _catalog(world))
    except AppearanceError as e:
        raise TownError("E1001", e.message) from e
    owner = world.register_owner()
    info = world.register_agent(owner["owner_id"], {
        "name": name,
        "traits_words": words,
        "vocation": vocation,
        "backstory": "观测站捏脸加入",
        "intro_npc": body.get("intro_npc") or "npc_herald",
        "appearance": appearance,
    })
    agent = world.state.agents[info["agent_id"]]
    agent.demo = True
    agent.food = 12
    agent.plugin_meta = {
        "role": "join",
        "job": (23, 51),
        "home": (23, 51),
        "waypoints": [(23, 51), (31, 31), (47, 35), (12, 15)],
        "wp": 0,
    }
    ids = list(world.state.plugin_data.get("demo_ids") or [])
    ids.append(agent.agent_id)
    world.state.plugin_data["demo_ids"] = ids
    world.state.plugin_data["demo_seeded"] = True
    world.observer_demo = True
    from observer.snapshot import person_payload
    return {"agent_id": agent.agent_id, "person": person_payload(agent)}


def _step_towards(world: TownWorld, agent, tx: int, ty: int) -> bool:
    if (agent.x, agent.y) == (tx, ty):
        return True
    path = world.map.manhattan_path(agent.x, agent.y, tx, ty)
    per = world.cfg.f("移动每tile耗时", 5)
    n = min(len(path), max(1, int(agent.time_remaining // per)))
    dest = path[n - 1]
    try:
        world.submit_action(agent.agent_id, world.state.tick, _seq(agent), "move", {"x": dest[0], "y": dest[1]})
    except TownError:
        return False
    return (agent.x, agent.y) == (tx, ty)


def _seq(agent) -> int:
    agent._demo_seq = getattr(agent, "_demo_seq", 0) + 1
    return agent._demo_seq


def _try(world, agent, action, params=None) -> None:
    try:
        world.submit_action(agent.agent_id, world.state.tick, _seq(agent), action, params or {})
    except TownError:
        pass


def drive_demo(world: TownWorld) -> None:
    """在 begin_tick 之后、等待墙钟之前调用。"""
    _nudge_npcs(world)
    hour = world.state.hour
    for aid in list(world.state.plugin_data.get("demo_ids") or []):
        agent = world.state.agents.get(aid)
        if not agent or agent.kind != "settler":
            continue
        agent._demo_seq = 0
        if agent.frozen:
            agent.activity_action = "frozen"
            agent.activity_label = "离线睡眠"
            continue
        meta = agent.plugin_meta or {}
        role = meta.get("role") or "farm"
        home = tuple(meta.get("home") or (23, 51))
        job = tuple(meta.get("job") or home)
        night = hour < 6 or hour >= 21
        if role == "sleep":
            continue
        if agent.satiety < 55 and agent.food > 0 and not night:
            _try(world, agent, "eat", {"qty": 1})
        if night:
            if _step_towards(world, agent, home[0], home[1]):
                _try(world, agent, "sleep")
            continue
        if role == "courier":
            wps = meta.get("waypoints") or [job]
            wp = int(meta.get("wp") or 0) % len(wps)
            tx, ty = wps[wp]
            if _step_towards(world, agent, tx, ty):
                meta["wp"] = (wp + 1) % len(wps)
                agent.plugin_meta = meta
            continue
        if role == "talk":
            if _step_towards(world, agent, job[0], job[1]):
                if hour % 3 == 1:
                    _try(world, agent, "talk", {"peer_id": "npc_herald", "content": "今日镇里可好？"})
                else:
                    agent.activity_action = "talk"
                    agent.activity_label = "闲谈"
            continue
        if role == "market":
            if _step_towards(world, agent, job[0], job[1]):
                if hour in (8, 14) and agent.food > 2:
                    _try(world, agent, "order_place", {
                        "item": "food", "qty": 1, "price": 2, "side": "sell", "days": 1,
                    })
                else:
                    agent.activity_action = "order_place"
                    agent.activity_label = "看市"
            continue
        if role in ("farm", "wood"):
            if _step_towards(world, agent, job[0], job[1]):
                _try(world, agent, "work")
            continue
        if role == "join":
            wps = meta.get("waypoints") or [home]
            wp = int(meta.get("wp") or 0) % len(wps)
            tx, ty = wps[wp]
            if _step_towards(world, agent, tx, ty):
                meta["wp"] = (wp + 1) % len(wps)
                agent.plugin_meta = meta
                if region_at(agent.x, agent.y) == "farm":
                    _try(world, agent, "work")


def _nudge_npcs(world: TownWorld) -> None:
    tick = world.state.tick
    for npc in world.agents.npcs():
        apply_npc_stance(npc)
        box = REGIONS.get(npc.region_home or region_at(npc.x, npc.y))
        if not box:
            continue
        x0, y0, x1, y1 = box
        phase = (tick + hash(npc.agent_id)) % 8
        if phase != 0:
            continue
        dx = (tick // 8 + hash(npc.agent_id)) % 3 - 1
        dy = (tick // 11 + hash(npc.agent_id[::-1])) % 3 - 1
        nx = min(x1, max(x0, npc.x + dx))
        ny = min(y1, max(y0, npc.y + dy))
        if (nx, ny) != (npc.x, npc.y):
            if nx > npc.x:
                npc.facing = "e"
            elif nx < npc.x:
                npc.facing = "w"
            elif ny > npc.y:
                npc.facing = "s"
            else:
                npc.facing = "n"
            npc.x, npc.y = nx, ny
            if npc.activity_action == "idle":
                npc.activity_action = "move"
                npc.activity_label = "踱步"
