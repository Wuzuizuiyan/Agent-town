from __future__ import annotations

import pytest

from world.kernel.world import TownWorld


def enroll(world: TownWorld, name="张三", x=8, y=15, **extra):
    owner = world.register_owner()
    card = {
        "name": name,
        "traits_words": ["稳重", "肯干", "老实"],
        "vocation": "农夫",
        "backstory": "来讨生活",
        "intro_npc": "npc_herald",
    }
    info = world.register_agent(owner["owner_id"], card)
    agent = world.state.agents[info["agent_id"]]
    agent.x, agent.y = x, y
    for k, v in extra.items():
        setattr(agent, k, v)
    return {**owner, **info, "agent": agent}


@pytest.fixture
def gun():
    return TownWorld(profile="first_gun")


@pytest.fixture
def full():
    return TownWorld(profile="full")
