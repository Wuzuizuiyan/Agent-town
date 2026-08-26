"""时钟、日志、RNG、需求与 agent 门面。"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone, timedelta
from typing import Any

from world.kernel.mapgrid import region_at
from world.kernel.state import Event, Relation, WorldState

TZ = timezone(timedelta(hours=8))


class Clock:
    def __init__(self, state: WorldState):
        self.state = state

    @property
    def tick(self) -> int:
        return self.state.tick

    @property
    def day(self) -> int:
        return self.state.day

    @property
    def hour(self) -> int:
        return self.state.hour

    @property
    def paused(self) -> bool:
        return self.state.paused


class Log:
    def __init__(self, state: WorldState):
        self.state = state

    def write(self, etype: str, actor: str | None = None, params: dict | None = None,
              result: str = "success", region: str | None = None, day: int | None = None) -> Event:
        ev = Event(
            tick=self.state.tick,
            day=self.state.day if day is None else day,
            ts=datetime.now(TZ).isoformat(),
            region=region,
            actor=actor,
            type=etype,
            params=params or {},
            result=result,
        )
        self.state.events.append(ev)
        return ev

    def system(self, etype: str, message: str) -> None:
        self.write(etype, actor="system", params={"message": message})

    def as_dict(self, ev: Event) -> dict[str, Any]:
        return {
            "tick": ev.tick,
            "day": ev.day,
            "timestamp": ev.ts,
            "region": ev.region,
            "actor": ev.actor,
            "type": ev.type,
            "params": ev.params,
            "result": ev.result,
        }


class Rng:
    def __init__(self, state: WorldState):
        self.state = state

    def stream(self, plugin_id: str, *parts: str) -> random.Random:
        raw = "|".join([self.state.seed, str(self.state.tick), plugin_id, *parts])
        h = hashlib.sha256(raw.encode()).hexdigest()
        return random.Random(int(h[:16], 16))


class Needs:
    def __init__(self, state: WorldState):
        self.state = state

    def clamp(self, agent_id: str) -> None:
        a = self.state.agents[agent_id]
        a.satiety = max(0.0, min(100.0, a.satiety))
        a.energy = max(0.0, min(100.0, a.energy))
        a.mood = max(0.0, min(100.0, a.mood))


class Agents:
    def __init__(self, state: WorldState):
        self.state = state

    def get(self, agent_id: str):
        return self.state.agents.get(agent_id)

    def settlers(self):
        return [a for a in self.state.agents.values() if a.kind == "settler"]

    def npcs(self):
        return [a for a in self.state.agents.values() if a.kind == "npc"]

    def region(self, agent) -> str:
        return region_at(agent.x, agent.y)

    def pair_key(self, a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)

    def relation(self, a: str, b: str):
        k = self.pair_key(a, b)
        rel = self.state.relations.get(k)
        if not rel:
            rel = Relation(a=k[0], b=k[1])
            self.state.relations[k] = rel
        return rel
