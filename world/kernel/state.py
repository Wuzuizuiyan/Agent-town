"""世界可变状态。插件通过服务读写，不互相 import。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Owner:
    owner_id: str
    token: str
    last_exit_day: int | None = None


@dataclass
class Agent:
    agent_id: str
    owner_id: str
    name: str
    token: str
    trait: str | None
    trait_words: list[str]
    vocation: str
    backstory: str
    intro_npc: str
    x: int
    y: int
    satiety: float = 100.0
    energy: float = 100.0
    mood: float = 50.0
    food: int = 0
    wood: int = 0
    coins_cents: int = 0
    receipt_food: int = 0
    receipt_wood: int = 0
    time_remaining: int = 60
    frozen: bool = False
    idle_ticks: int = 0
    slept: bool = False
    enrolled_day: int = 1
    house_id: str | None = None
    warehouse_id: str | None = None
    farmer_hours: float = 0.0
    woodcutter_hours: float = 0.0
    day_hours: dict[str, float] = field(default_factory=dict)
    reputation: float = 50.0
    defaults: int = 0
    rank: str = "resident"
    loan_ban_until: int = 0
    mode: str = "pull"
    webhook_url: str | None = None
    webhook_fail: int = 0
    acted_this_tick: bool = False
    talks_this_tick: int = 0
    intel_this_tick: int = 0
    perception_tick: int | None = None
    kind: str = "settler"  # settler | npc
    npc_id: str | None = None
    region_home: str | None = None
    last_region_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass
class Freeze:
    freeze_id: str
    agent_id: str
    item: str
    qty: int
    document_id: str


@dataclass
class Order:
    order_id: str
    agent_id: str
    item: str
    qty: int
    price_cents: int
    side: str
    created_tick: int
    expire_day: int
    system: bool = False
    caravan: bool = False
    remaining: int = 0

    def __post_init__(self):
        if not self.remaining:
            self.remaining = self.qty


@dataclass
class Building:
    building_id: str
    kind: str
    venue_kind: str
    effect_kind: str
    x: int
    y: int
    w: int
    h: int
    status: str  # pledged | building | done | wasted
    owner_id: str | None = None
    waste_count: int = 0
    last_work_day: int | None = None
    unlocked: bool = False


@dataclass
class Project:
    project_id: str
    building: str
    venue_kind: str
    effect_kind: str
    x: int
    y: int
    w: int
    h: int
    initiator: str
    status: str  # pledging | building | done | failed | cancelled
    need_wood: int = 0
    need_coins_cents: int = 0
    need_hours: int = 0
    pledged_wood: int = 0
    pledged_coins_cents: int = 0
    pledged_hours: int = 0
    delivered_hours: int = 0
    pledges: dict[str, dict[str, int]] = field(default_factory=dict)
    created_day: int = 1
    build_deadline_day: int | None = None
    deposit_cents: int = 0
    category: str = "建造类"


@dataclass
class Document:
    document_id: str
    kind: str
    payload: dict[str, Any]
    status: str = "pending"
    created_tick: int = 0
    expire_tick: int = 0


@dataclass
class Event:
    tick: int
    day: int
    ts: str
    region: str | None
    actor: str | None
    type: str
    params: dict[str, Any]
    result: str = "success"


@dataclass
class Relation:
    a: str
    b: str
    value: float = 0.0
    interact_count: int = 0
    last_tick: int = 0
    gain_today: float = 0.0
    loss_today: float = 0.0


@dataclass
class WorldState:
    tick: int = 0
    day: int = 1
    hour: int = 0
    paused: bool = False
    speed: float = 1.0
    in_tick: bool = False
    matching: bool = False
    public_pool_cents: int = 0
    seed: str = "town"
    owners: dict[str, Owner] = field(default_factory=dict)
    agents: dict[str, Agent] = field(default_factory=dict)
    tokens: dict[str, tuple[str, str]] = field(default_factory=dict)  # token -> (kind, id)
    freezes: list[Freeze] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    buildings: dict[str, Building] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    documents: dict[str, Document] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    relations: dict[tuple[str, str], Relation] = field(default_factory=dict)
    inbox: dict[str, dict[str, list]] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    open_farm: set[tuple[int, int]] = field(default_factory=set)
    open_forest: set[tuple[int, int]] = field(default_factory=set)
    waste_farm: set[tuple[int, int]] = field(default_factory=set)
    dense_forest: set[tuple[int, int]] = field(default_factory=set)
    unlocked_forest: set[tuple[int, int]] = field(default_factory=set)
    roads: set[tuple[int, int]] = field(default_factory=set)
    anchors: dict[str, int] = field(default_factory=lambda: {"food": 200, "wood": 300})
    day_trades: list[dict] = field(default_factory=list)
    tax_free_used: dict[str, int] = field(default_factory=dict)
    active_events: list[dict] = field(default_factory=list)
    npc_attitudes: dict[tuple[str, str], float] = field(default_factory=dict)
    bounties: list[dict] = field(default_factory=list)
    bulletins: list[dict] = field(default_factory=list)
    blueprints: dict[str, dict] = field(default_factory=dict)
    plebiscites: dict[str, dict] = field(default_factory=dict)
    election: dict | None = None
    mayor_id: str = "npc_mayor"
    mayor_term_end: int = 7
    gazette: dict | None = None
    plugin_data: dict[str, Any] = field(default_factory=dict)
    idle_skip_daily: bool = False
    last_day_traded: dict[str, int] = field(default_factory=dict)
    config_errors: list[str] = field(default_factory=list)
    stepping: bool = False
    stats: dict[str, Any] = field(default_factory=dict)
    event_forecast: list[dict] = field(default_factory=list)

    def nid(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}_{self.counters[prefix]:04d}"
