"""世界编排：内核管线 + 插件加载。move / HTTP / 账本 / 地图属内核。"""

from __future__ import annotations

import importlib
import os
import secrets
from pathlib import Path
from typing import Any

import yaml

from world.kernel.bus import PluginBus
from world.kernel.config import ConfigSnapshot
from world.kernel.errors import TownError
from world.kernel.ledger import Ledger
from world.kernel.mapgrid import MapService, init_open_tiles, region_at, bbox_tiles
from world.kernel.money import coins_to_cents, cents_to_coins
from world.kernel.services import Agents, Clock, Log, Needs, Rng
from world.kernel.state import Agent, Building, Owner, WorldState
from world.kernel.util import (
    charge_time,
    manhattan,
    mood_mul,
    prof_rank,
    rank_of,
    require_not_frozen,
    restore_state,
    snapshot_state,
)

PLUGIN_MODULES = {
    "survival": "world.plugins.survival.plugin",
    "market": "world.plugins.market.plugin",
    "social": "world.plugins.social.plugin",
    "construction": "world.plugins.construction.plugin",
    "contracts": "world.plugins.contracts.plugin",
    "governance": "world.plugins.governance.plugin",
    "bounty": "world.plugins.bounty.plugin",
    "npc": "world.plugins.npc.plugin",
    "events": "world.plugins.events.plugin",
}

REGION_NPC_XY = {
    "well": (3, 31),
    "town_hall": (31, 31),
    "farm": (8, 15),
    "forest": (32, 15),
    "market": (47, 35),
    "residential": (23, 51),
}


class TownWorld:
    def __init__(self, root: str | Path | None = None, profile: str | list[str] = "full",
                 gm_token: str = "dev-gm-token"):
        self.root = Path(root or Path(__file__).resolve().parents[2])
        self.cfg = ConfigSnapshot(self.root)
        self.state = WorldState()
        self.state.public_pool_cents = coins_to_cents(self.cfg.f("公共池初始注资", 500), self.places)
        self.state.anchors = {
            "food": coins_to_cents(self.cfg.f("阿市锚价_食物", 2), self.places),
            "wood": coins_to_cents(self.cfg.f("阿市锚价_木材", 3), self.places),
        }
        self.gm_token = gm_token
        self.state.tokens[gm_token] = ("gm", "gm")
        init_open_tiles(self.state)
        self._place_well()
        self._services_init()
        self.bus = PluginBus(self.services)
        self._register_kernel_move()
        names = self._resolve_profile(profile)
        self.profile = names
        self._load_plugins(names)
        self._spawn_npcs()

    @property
    def places(self) -> int:
        return int(self.cfg.f("镇币小数位", 2))

    def _services_init(self) -> None:
        self.clock = Clock(self.state)
        self.map = MapService(self.state)
        self.ledger = Ledger(self.state, self.places)
        self.agents = Agents(self.state)
        self.needs = Needs(self.state)
        self.log = Log(self.state)
        self.rng = Rng(self.state)
        self.services = {
            "clock": self.clock,
            "map": self.map,
            "ledger": self.ledger,
            "agents": self.agents,
            "needs": self.needs,
            "log": self.log,
            "rng": self.rng,
            "config": self.cfg,
            "world": self,
            "perception": self,
            "llm": TemplateLLM(),
        }

    def _place_well(self) -> None:
        bx = self.cfg.i("初始水井x", 3)
        by = self.cfg.i("初始水井y", 31)
        bid = "bd_well"
        self.state.buildings[bid] = Building(
            building_id=bid, kind="well", venue_kind="well", effect_kind="well",
            x=bx, y=by, w=1, h=1, status="done",
        )

    def _resolve_profile(self, profile: str | list[str]) -> list[str]:
        if isinstance(profile, list):
            return list(profile)
        path = self.root / "world" / "profiles" / f"{profile}.yml"
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return list(data.get("plugins") or [])
        if profile == "full":
            return list(PLUGIN_MODULES)
        if profile == "first_gun":
            return ["survival", "market"]
        return ["survival", "market"]

    def _load_plugins(self, names: list[str]) -> None:
        for name in names:
            mod_name = PLUGIN_MODULES[name]
            mod = importlib.import_module(mod_name)
            inject = list(getattr(mod, "INJECT", []))
            self.bus.load(name, inject, mod.apply)

    def reload_plugins(self, names: list[str]) -> None:
        if not self.state.paused and self.state.in_tick:
            raise TownError("E1014", "仅暂停或 tick 间隙可装卸插件")
        self.bus.unload_all()
        self.profile = list(names)
        self._load_plugins(names)

    def _register_kernel_move(self) -> None:
        def handle_move(actor: Agent, params: dict) -> dict:
            require_not_frozen(actor)
            if "x" not in params or "y" not in params:
                raise TownError("E1001")
            x, y = int(params["x"]), int(params["y"])
            if not self.map.enterable(x, y):
                raise TownError("E1003")
            dist = manhattan(actor.x, actor.y, x, y)
            if dist == 0:
                return {"moved": False}
            per = self.cfg.f("移动每tile耗时", 5)
            path = [(actor.x, actor.y)] + self.map.manhattan_path(actor.x, actor.y, x, y)
            if self.map.all_road(path):
                per = self.cfg.f("道路每tile耗时", 3)
            if actor.energy >= self.cfg.f("精力充沛阈值", 70):
                per *= self.cfg.f("精力充沛移动耗时折减", 0.8)
            if any(e["name"] == "storm" for e in self.state.active_events):
                per += self.cfg.f("事件_暴风雨移动耗时增量", 3)
            cost = int(dist * per)
            charge_time(actor, cost)
            actor.x, actor.y = x, y
            return {"x": x, "y": y, "cost": cost}

        self.bus.actions["move"] = handle_move

    def _spawn_npcs(self) -> None:
        for row in self.cfg.npcs:
            nid = row.get("npc_id") or ""
            if not nid:
                continue
            # 建筑激活 / 事件到访：未激活不刷
            if nid in ("npc_cook", "npc_keeper", "npc_trader"):
                continue
            region_cn = (row.get("常驻区域") or "公所").split("（")[0]
            from world.kernel.mapgrid import CN_REGION
            api = CN_REGION.get(region_cn, "town_hall")
            x, y = REGION_NPC_XY.get(api, (31, 31))
            aid = nid
            token = secrets.token_urlsafe(8)
            ag = Agent(
                agent_id=aid, owner_id="system", name=row.get("NPC名") or nid,
                token=token, trait=None,
                trait_words=(row.get("性格三词") or "").split(),
                vocation=row.get("职能") or "", backstory="", intro_npc="",
                x=x, y=y, kind="npc", npc_id=nid, region_home=api,
                satiety=100, energy=100, mood=50, food=0, wood=0, coins_cents=0,
            )
            self.state.agents[aid] = ag

    def register_owner(self, invite_code: str | None = None) -> dict:
        if self.cfg.i("入驻邀请码开关", 0) == 1:
            allowed = [s.strip() for s in os.environ.get("TOWN_INVITE_CODES", "").split(",") if s.strip()]
            if not invite_code or invite_code not in allowed:
                raise TownError("E1001", "邀请码无效")
        oid = self.state.nid("ow")
        token = secrets.token_urlsafe(24)
        self.state.owners[oid] = Owner(oid, token)
        self.state.tokens[token] = ("owner", oid)
        return {"owner_id": oid, "owner_token": token}

    def register_agent(self, owner_id: str, card: dict, mode: str = "pull",
                       webhook_url: str | None = None) -> dict:
        owner = self.state.owners[owner_id]
        for a in self.agents.settlers():
            if a.owner_id == owner_id:
                raise TownError("E1039")
        if owner.last_exit_day is not None:
            if self.state.day - owner.last_exit_day < self.cfg.i("再入驻冷却", 3):
                raise TownError("E1039")
        name = (card.get("name") or "").strip()
        words = card.get("traits_words") or card.get("personality") or []
        if isinstance(words, str):
            words = words.split()
        vocation = (card.get("vocation") or "-").strip()
        backstory = card.get("backstory") or ""
        intro = card.get("intro_npc") or ""
        trait = card.get("trait") or None
        if not (1 <= len(name) <= 12):
            raise TownError("E1001")
        if len(words) != 3:
            raise TownError("E1001")
        if not (1 <= len(vocation) <= 8):
            raise TownError("E1001")
        if len(backstory) > 200:
            raise TownError("E1001")
        npc = self.cfg.npc_by_id_or_name(intro)
        if not npc:
            raise TownError("E1001")
        if trait:
            if trait not in self.cfg.traits:
                raise TownError("E1001")
            trait = self.cfg.traits[trait].get("特质名") or trait
        if mode == "push" and not webhook_url:
            raise TownError("E1001")
        aid = self.state.nid("a")
        token = secrets.token_urlsafe(24)
        x, y = self.cfg.i("投放坐标x", 23), self.cfg.i("投放坐标y", 51)
        ag = Agent(
            agent_id=aid, owner_id=owner_id, name=name, token=token,
            trait=trait, trait_words=list(words), vocation=vocation,
            backstory=backstory, intro_npc=npc.get("npc_id") or intro,
            x=x, y=y, enrolled_day=self.state.day, mode=mode,
            webhook_url=webhook_url,
            food=self.cfg.i("初始食物", 8),
            coins_cents=coins_to_cents(self.cfg.f("启动金", 20), self.places),
            reputation=self.cfg.f("声誉基础分", 50),
            rank=rank_of(self.cfg.f("声誉基础分", 50), self.cfg),
        )
        self.state.agents[aid] = ag
        self.state.tokens[token] = ("agent", aid)
        self.state.inbox.setdefault(aid, {"unread_dialogues": [], "trade_notices": [],
                                          "pledge_notices": [], "intel_shares": [], "gm_facts": []})
        rel = self.agents.relation(aid, npc.get("npc_id"))
        rel.value = 20
        self.log.write("AGENT_ACTION", actor=aid, params={"action": "register", "name": name})
        return {"agent_id": aid, "agent_token": token, "mode": mode}

    def begin_tick(self) -> None:
        if self.state.paused:
            raise TownError("E1014")
        self.state.tick += 1
        self.state.hour = (self.state.tick - 1) % 24
        self.state.day = (self.state.tick - 1) // 24 + 1
        self.state.in_tick = True
        self.state.matching = False
        if self.state.hour == 0 and self.state.tick > 1:
            self._daily_settle()
        budget = self.cfg.i("每tick时间预算", 60)
        for a in self.agents.settlers():
            a.time_remaining = budget
            a.slept = False
            a.acted_this_tick = False
            a.talks_this_tick = 0
            a.intel_this_tick = 0
        self.bus.run_hooks("tick", 1, self)

    def end_tick(self) -> None:
        freeze_th = self.cfg.i("冻结阈值", 48)
        for a in self.agents.settlers():
            if a.acted_this_tick:
                a.idle_ticks = 0
            else:
                a.idle_ticks += 1
                if a.idle_ticks >= freeze_th and not a.frozen:
                    a.frozen = True
                    self.log.write("FREEZE", actor=a.agent_id)
        self.bus.run_hooks("tick", 3, self)
        self.state.matching = True
        try:
            self.bus.run_hooks("tick", 4, self)
        except Exception:
            self.log.system("SETTLE_ERROR", "撮合失败，本 tick 作废")
        self.state.matching = False
        self.bus.run_hooks("tick", 5, self)
        self.state.in_tick = False

    def step(self, n: int = 1) -> None:
        if self.state.paused:
            raise TownError("E1014")
        for _ in range(n):
            self.begin_tick()
            self.end_tick()

    def _daily_settle(self) -> None:
        self._reload_config()
        self.bus.run_hooks("daily", 1, self)
        self.bus.run_hooks("daily", 2, self)
        self.bus.run_hooks("daily", 3, self)
        self.bus.run_hooks("daily", 4, self)
        self.bus.run_hooks("daily", 5, self)
        self.bus.run_hooks("daily", 6, self)
        self.bus.run_hooks("daily", 7, self)
        self._compute_stats()
        self.bus.run_hooks("daily", 8, self)
        self._build_gazette()
        self.bus.run_hooks("daily", 9, self)
        for a in self.agents.settlers():
            a.day_hours = {}
        self.state.day_trades = []
        self.state.tax_free_used = {}
        settled = self.state.day - 1 if self.state.hour == 0 else self.state.day
        self.log.write("DAY_SETTLE", params={"day": settled})

    def submit_action(self, agent_id: str, tick: int, seq: int, action: str,
                      params: dict | None = None) -> dict:
        if self.state.paused or self.state.stepping:
            raise TownError("E1014")
        if not self.state.in_tick:
            raise TownError("E1014", "当前不在可提交窗口（请先 begin_tick 或走 HTTP 时钟）")
        agent = self.state.agents.get(agent_id)
        if not agent or agent.kind != "settler":
            raise TownError("E1001")
        if tick != self.state.tick:
            raise TownError("E1001", "tick 不匹配")
        params = dict(params or {})
        handler = self.bus.action_handler(action)
        if handler is None:
            raise TownError("E1001", f"未知动作或插件未加载: {action}")
        key = (tick, agent.token, action, seq)
        cache = self.state.plugin_data.setdefault("_idem", {})
        if key in cache:
            out = dict(cache[key])
            out["idempotent"] = True
            return out
        sub_key = None
        if action.endswith("_confirm") or action in (
            "loan_repay", "contract_terminate", "vote_election",
            "blueprint_support", "vote_plebiscite", "intel_confirm",
            "guarantee_confirm", "transfer_confirm", "hire_confirm",
            "labor_accept", "trade_confirm",
        ):
            sub_key = (params.get("document_id") or params.get("loan_id") or params.get("contract_id")
                       or params.get("candidate_id") or params.get("blueprint_id")
                       or params.get("plebiscite_id"), action)
            if sub_key in cache:
                out = dict(cache[sub_key])
                out["idempotent"] = True
                return out
        snap = snapshot_state(self.state)
        try:
            result = handler(agent, params) or {}
            agent.acted_this_tick = True
            self.log.write(
                "AGENT_ACTION", actor=agent_id,
                params={"action": action, "seq": seq, "params": params, "result": result},
                region=region_at(agent.x, agent.y),
            )
            payload = {
                "accepted": True,
                "time_remaining": agent.time_remaining,
                "idempotent": False,
                "result": result,
            }
            cache[key] = payload
            if sub_key:
                cache[sub_key] = payload
            return payload
        except TownError as e:
            restore_state(self.state, snap)
            self.log.write(
                "AGENT_ACTION", actor=agent_id,
                params={"action": action, "seq": seq, "error": e.code},
                result="rejected",
                region=region_at(agent.x, agent.y),
            )
            raise
        except Exception as e:
            restore_state(self.state, snap)
            self.log.system("SETTLE_ERROR", str(e))
            raise TownError("E1001", "动作执行异常") from e

    def perception(self, agent_id: str, tick: int | None = None) -> dict:
        agent = self.state.agents.get(agent_id)
        if not agent:
            raise TownError("E1001")
        t = self.state.tick if tick is None else tick
        if tick is not None and tick != self.state.tick:
            stored = (self.state.plugin_data.get("_perc") or {}).get(agent_id, {}).get(tick)
            if stored is None:
                raise TownError("E1001", "无该 tick 感知缓存")
            return stored
        if tick is None or tick == self.state.tick:
            if agent.perception_tick == self.state.tick:
                raise TownError("E1013")
            agent.perception_tick = self.state.tick
        region = region_at(agent.x, agent.y)
        venue = self.map.venue_at(agent.x, agent.y)
        present = self.map.occupants(region)
        traits = {}
        for oid in present:
            other = self.state.agents.get(oid)
            if other and other.trait:
                traits[oid] = self.cfg.trait_api(other.trait)
        pack = {
            "tick": t,
            "day": self.state.day,
            "active_events": list(self.state.active_events),
            "self": self._self_view(agent),
            "region": {
                "type": region,
                "venue": venue,
                "resources": self._resources(region),
                "agents_present": present,
                "traits_present": traits or None,
                "market_board": None,
                "projects_onsite": None,
                "reputation_board": None,
                "bulletin_board": None,
                "market_summary": None,
                "gov_board": None,
                "blueprints": None,
                "plebiscites": None,
                "bounty_board": None,
            },
            "inbox": self.state.inbox.get(agent_id, {
                "unread_dialogues": [], "trade_notices": [], "pledge_notices": [],
                "intel_shares": [], "gm_facts": [],
            }),
        }
        for (scope, key), fn in self.bus.perception.items():
            try:
                val = fn(agent, pack)
            except Exception:
                continue
            if scope == "region" and val is not None:
                pack["region"][key] = val
            elif scope == "self" and val is not None:
                pack["self"][key] = val
            elif scope == "inbox" and val is not None:
                pack["inbox"][key] = val
        agent.last_region_snapshot[region] = {
            "tick": self.state.tick,
            "resources": pack["region"]["resources"],
            "agents_present": present,
            "market_board": pack["region"].get("market_board"),
        }
        hist = self.state.plugin_data.setdefault("_perc", {})
        agent_hist = hist.setdefault(agent_id, {})
        agent_hist[t] = pack
        extra = sorted(k for k in agent_hist if k < t - 48)
        for old in extra:
            agent_hist.pop(old, None)
        return pack

    def _self_view(self, agent: Agent) -> dict:
        assets = []
        for b in self.state.buildings.values():
            if b.owner_id == agent.agent_id:
                assets.append({
                    "asset_id": b.building_id,
                    "type": b.venue_kind,
                    "position": {"x": b.x, "y": b.y},
                    "waste_count": b.waste_count,
                    "status": b.status,
                })
        rels = []
        for rel in self.state.relations.values():
            if agent.agent_id in (rel.a, rel.b):
                other = rel.b if rel.a == agent.agent_id else rel.a
                o = self.state.agents.get(other)
                rels.append({
                    "agent_id": other,
                    "name": o.name if o else other,
                    "value": rel.value,
                    "interact_count": rel.interact_count,
                    "last_interact_tick": rel.last_tick,
                })
        restrictions = []
        if agent.loan_ban_until >= self.state.day:
            restrictions.append({"type": "loan_ban", "until_day": agent.loan_ban_until})
        standing = []
        for d in self.state.documents.values():
            if d.kind.startswith("standing") and d.payload.get("agent_id") == agent.agent_id and d.status == "active":
                standing.append({
                    "order_id": d.document_id,
                    "type": d.payload.get("type"),
                    "trigger": d.payload.get("trigger"),
                    "days_left": d.payload.get("expire_day", 0) - self.state.day,
                    "frozen": d.payload.get("frozen"),
                })
        loans = []
        contracts = []
        for d in self.state.documents.values():
            if d.kind == "loan" and d.status == "active" and agent.agent_id in (
                d.payload.get("borrower"), d.payload.get("lender")
            ):
                loans.append({
                    "loan_id": d.document_id,
                    "side": "borrow" if d.payload.get("borrower") == agent.agent_id else "lend",
                    "principal": cents_to_coins(d.payload.get("principal_cents", 0), self.places),
                    "due_day": d.payload.get("due_day"),
                    "status": d.status,
                })
            if d.kind in ("hire", "labor_transfer") and d.status == "active":
                if agent.agent_id in (d.payload.get("employer"), d.payload.get("worker"),
                                      d.payload.get("from"), d.payload.get("to")):
                    role = "worker" if agent.agent_id == d.payload.get("worker") else "employer"
                    contracts.append({
                        "contract_id": d.document_id,
                        "kind": d.kind,
                        "type": d.payload.get("type", "fixed_wage"),
                        "role": role,
                        "hours_total": d.payload.get("hours_total"),
                        "hours_delivered": d.payload.get("hours_delivered", 0),
                        "days_left": (d.payload.get("due_day") or self.state.day) - self.state.day,
                        "status": d.status,
                    })
        return {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "enrolled_day": agent.enrolled_day,
            "position": {
                "x": agent.x, "y": agent.y,
                "region": region_at(agent.x, agent.y),
                "venue": self.map.venue_at(agent.x, agent.y),
            },
            "needs": {"satiety": round(agent.satiety, 2), "energy": round(agent.energy, 2),
                      "mood": round(agent.mood, 2)},
            "inventory": self.ledger.inventory(agent.agent_id),
            "bindings": {"house": agent.house_id, "warehouse": agent.warehouse_id},
            "assets": assets,
            "relations": rels,
            "proficiency": {
                "farmer": {"hours": agent.farmer_hours, "rank": prof_rank(agent.farmer_hours, self.cfg)},
                "woodcutter": {"hours": agent.woodcutter_hours, "rank": prof_rank(agent.woodcutter_hours, self.cfg)},
            },
            "reputation": {"score": round(agent.reputation, 2), "defaults": agent.defaults, "rank": agent.rank},
            "loans": loans,
            "contracts": contracts,
            "restrictions": restrictions,
            "time_remaining": agent.time_remaining,
            "standing_orders": standing,
        }

    def _resources(self, region: str) -> dict:
        if region == "farm":
            claim = len([t for t in self.state.waste_farm if t not in {
                (b.x, b.y) for b in self.state.buildings.values()
            }])
            return {"open_tiles": len(self.state.open_farm), "claimable_tiles": claim,
                    "population": len(self.map.occupants(region))}
        if region == "forest":
            claim = len(self.state.unlocked_forest)
            return {"open_tiles": len(self.state.open_forest), "claimable_tiles": claim,
                    "population": len(self.map.occupants(region))}
        return {"open_tiles": None, "claimable_tiles": None, "population": len(self.map.occupants(region))}

    def freeze_agent(self, agent_id: str) -> None:
        a = self.state.agents[agent_id]
        a.frozen = True
        self.log.write("FREEZE", actor=agent_id)

    def unfreeze_agent(self, agent_id: str) -> None:
        a = self.state.agents[agent_id]
        a.frozen = False
        a.idle_ticks = 0
        self.log.write("UNFREEZE", actor=agent_id)

    def set_paused(self, paused: bool) -> None:
        self.state.paused = paused
        self.log.write("SPEED_CHANGE", params={"pause": paused, "speed": self.state.speed})

    def set_speed(self, multiplier: float) -> None:
        legal = {0.5, 1, 2, 4, 16, 60, 3600}
        if multiplier not in legal:
            raise TownError("E1001")
        self.state.speed = float(multiplier)
        self.state.paused = False
        self.log.write("SPEED_CHANGE", params={"speed": multiplier})

    def kick(self, agent_id: str) -> None:
        a = self.state.agents.get(agent_id)
        if not a or a.kind != "settler":
            raise TownError("E1001")
        owner = self.state.owners.get(a.owner_id)
        if owner:
            owner.last_exit_day = self.state.day
        self.ledger.unfreeze_doc(agent_id)
        for d in list(self.state.documents.values()):
            if d.status == "pending":
                d.status = "cancelled"
                self.ledger.unfreeze_doc(d.document_id)
        self.state.orders = [o for o in self.state.orders if o.agent_id != agent_id]
        self.state.tokens.pop(a.token, None)
        self.state.agents.pop(agent_id, None)
        self.log.write("AGENT_ACTION", actor=agent_id, params={"action": "exit"})

    def auth(self, token: str) -> tuple[str, str]:
        if token not in self.state.tokens:
            raise TownError("E1001", "鉴权失败")
        return self.state.tokens[token]

    def reissue_agent_token(self, owner_id: str, agent_id: str) -> dict:
        a = self.state.agents.get(agent_id)
        if not a or a.owner_id != owner_id or a.kind != "settler":
            raise TownError("E1001")
        self.state.tokens.pop(a.token, None)
        token = secrets.token_urlsafe(24)
        a.token = token
        self.state.tokens[token] = ("agent", agent_id)
        return {"agent_id": agent_id, "agent_token": token}

    def gm_step(self, ticks: int) -> None:
        cap = self.cfg.i("GM推进最大tick", 24)
        if ticks < 1 or ticks > cap:
            raise TownError("E1001")
        self.state.stepping = True
        was = self.state.paused
        self.state.paused = False
        try:
            self.step(ticks)
        finally:
            self.state.paused = was
            self.state.stepping = False
            self.log.write("SPEED_CHANGE", params={"step": ticks, "speed": self.state.speed})

    def gm_inject(self, target: str, content: str) -> None:
        ids = list(self.agents.settlers()) if target == "all" else [self.state.agents.get(target)]
        for a in ids:
            if not a or a.kind != "settler":
                continue
            box = self.state.inbox.setdefault(a.agent_id, {
                "unread_dialogues": [], "trade_notices": [], "pledge_notices": [],
                "intel_shares": [], "gm_facts": [],
            })
            box["gm_facts"].append({"content": content, "tick": self.state.tick})
        self.log.write("GM_INJECT", params={"target": target, "content": content})

    def gm_blueprint(self, blueprint_id: str, decision: str, footprint: dict | None = None) -> dict:
        bp = self.state.blueprints.get(blueprint_id)
        if not bp or bp.get("status") != "review":
            raise TownError("E1031")
        if decision == "reject":
            bp["status"] = "rejected"
            self.log.write("BLUEPRINT", params={"id": blueprint_id, "op": "reject"})
            return {"status": "rejected"}
        if decision != "approve" or not footprint:
            raise TownError("E1031")
        ek = footprint.get("effect_kind")
        if not ek or ek not in self.bus.effect_kinds:
            raise TownError("E1031", "效果键未登记")
        from world.kernel.mapgrid import CN_REGION
        rev = {v: k for k, v in CN_REGION.items()}
        region = footprint.get("region") or ""
        region_cn = rev.get(region, region)
        row = {
            "建筑名称": bp.get("name") or "",
            "类别": "建造类" if bp.get("category") in ("build", "建造类") else "改造类",
            "木材需求": str(bp.get("wood") or 0),
            "镇币需求": str(bp.get("coins") or 0),
            "工时需求": str(bp.get("hours") or 0),
            "来源": "图纸",
            "效果值": str(bp.get("effect") or ""),
            "荒废规则": "",
            "说明": "",
            "占地宽": str(footprint.get("w") or 1),
            "占地高": str(footprint.get("h") or 1),
            "允许区域": region_cn,
            "场所键": str(footprint.get("venue_kind") or ""),
            "效果键": ek,
            "办理地点": "",
        }
        if not row["建筑名称"] or int(row["占地宽"]) < 1 or int(row["占地高"]) < 1:
            raise TownError("E1031")
        names = {b.get("建筑名称") for b in self.cfg.buildings}
        if row["建筑名称"] in names:
            raise TownError("E1031", "建筑名称冲突")
        self.state.plugin_data.setdefault("pending_buildings", []).append(row)
        bp["status"] = "approved"
        self.log.write("BLUEPRINT", params={"id": blueprint_id, "op": "approve", "effect_kind": ek})
        return {"status": "approved"}

    def gm_bounty(self, params: dict) -> dict:
        if not self.bus.has("bounty"):
            raise TownError("E1001", "bounty 插件未加载")
        typ = params.get("type")
        if typ not in ("labor", "build", "complete"):
            raise TownError("E1041")
        days = int(params.get("days") or 0)
        if days < 1 or days > self.cfg.i("悬赏期限上限", 3):
            raise TownError("E1041")
        cap = coins_to_cents(params.get("cap") or 0, self.places)
        if self.state.public_pool_cents < cap:
            self.log.system("SETTLE_ERROR", "GM 悬赏池余额不足")
            raise TownError("E1008", "公共池余额不足")
        bid = self.state.nid("by")
        self.state.bounties.append({
            "id": bid, "type": typ, "target": params.get("target"),
            "rate": float(params.get("rate") or self.cfg.f("悬赏_例行劳作单价", 0.15)),
            "cap_cents": cap, "remain_cents": cap,
            "expire_day": self.state.day + days, "status": "active",
            "from": "gm",
        })
        self.log.write("BOUNTY", params={"id": bid, "op": "post", "source": "GM"})
        return {"bounty_id": bid}

    def chronicle(self) -> list[dict]:
        out = []
        for ev in self.state.events:
            item = self._chronicle_item(ev)
            if item:
                out.append({**self.log.as_dict(ev), "chronicle": item})
        return out

    def _chronicle_item(self, ev) -> str | None:
        p = ev.params or {}
        if ev.type == "AGENT_ACTION" and p.get("action") == "register":
            a = self.state.agents.get(ev.actor)
            name = (a.name if a else None) or p.get("name") or ev.actor
            return f"{ev.actor} {name} 于第 {ev.day} 日入驻"
        if ev.type == "AGENT_ACTION" and p.get("action") == "exit":
            return f"{ev.actor} 于第 {ev.day} 日离开小镇"
        if ev.type == "BUILDING_DONE":
            return f"{p.get('kind')} 落成（项目 {p.get('project_id')}）"
        if ev.type == "LOAN_DEFAULT":
            return f"{ev.actor} 于第 {ev.day} 日借贷违约"
        if ev.type == "CONTRACT" and p.get("op") == "breach":
            return f"{p.get('by')} 于第 {ev.day} 日雇佣违约"
        if ev.type == "ELECTION" and p.get("op") == "tally":
            return f"{p.get('mayor')} 于第 {ev.day} 日当选镇长"
        if ev.type == "PROJECT_UPDATE" and p.get("op") == "fail":
            return f"项目 {p.get('project_id')} 流拍（发起人见日志）"
        return None

    def _reload_config(self) -> None:
        prev = dict(self.cfg.world)
        self.cfg.load()
        if int(self.cfg.f("季节周期", 7)) != 7:
            self.cfg.world["季节周期"] = prev.get("季节周期", "7")
            self.log.system("SETTLE_ERROR", "季节周期非法，保留旧值")
        pending = self.state.plugin_data.pop("pending_buildings", [])
        for row in pending:
            ek = row.get("效果键")
            if ek and ek not in self.bus.effect_kinds:
                self.log.system("SETTLE_ERROR", f"图纸增行效果键未登记: {ek}")
                continue
            try:
                if int(row.get("占地宽") or 0) < 1 or int(row.get("占地高") or 0) < 1:
                    self.log.system("SETTLE_ERROR", "图纸增行占地非法")
                    continue
            except ValueError:
                self.log.system("SETTLE_ERROR", "图纸增行占地非法")
                continue
            self.cfg.buildings.append(row)
        self.log.write("CONFIG_RELOAD", params={"pending": len(pending)})

    def _compute_stats(self) -> None:
        settlers = self.agents.settlers()
        job_hours = {"farm": 0.0, "wood": 0.0, "build": 0.0, "odd": 0.0, "forage": 0.0}
        for a in settlers:
            job_hours["farm"] += a.day_hours.get("farm", 0) + a.day_hours.get("paddy", 0) + a.day_hours.get("farm_plot", 0)
            job_hours["wood"] += a.day_hours.get("wood", 0) + a.day_hours.get("forest_plot", 0)
            job_hours["odd"] += a.day_hours.get("odd", 0)
            job_hours["forage"] += a.day_hours.get("forage", 0)
        total_h = sum(job_hours.values()) or 1.0
        by_item: dict[str, list] = {}
        for t in self.state.day_trades:
            by_item.setdefault(t["item"], []).append(t)
        prices = {}
        for item, ts in by_item.items():
            vol = sum(x["qty"] for x in ts) or 1
            prices[item] = {
                "volume": vol,
                "wavg": sum(x["qty"] * x["price_cents"] for x in ts) / vol,
            }
        cents = sorted(a.coins_cents for a in settlers)
        gini = 0.0
        if cents:
            n = len(cents)
            tot = sum(cents) or 1
            acc = 0
            for i, c in enumerate(cents, 1):
                acc += c
                gini += (2 * i - n - 1) * c
            gini = gini / (n * tot)
        yday = self.state.day - 1
        mint = sum(ev.params.get("cents", 0) for ev in self.state.events if ev.type == "MINT" and ev.day == yday)
        hires = sum(1 for d in self.state.documents.values() if d.kind == "hire" and d.status == "active")
        loans = sum(1 for d in self.state.documents.values() if d.kind == "loan" and d.status == "active")
        self.state.stats = {
            "jobs": {k: round(v / total_h, 4) for k, v in job_hours.items()},
            "prices": prices,
            "gini": gini,
            "buildings": len([b for b in self.state.buildings.values() if b.status == "done"]),
            "hires": hires,
            "loans": loans,
            "mint_cents": mint,
            "pool": self.state.public_pool_cents,
            "population": len(settlers),
        }

    def _build_gazette(self) -> None:
        from world.kernel.util import season_of
        yday = self.state.day - 1
        headlines = []
        for ev in self.state.events:
            if ev.day != yday:
                continue
            item = self._chronicle_item(ev)
            if item:
                headlines.append(item)
            if ev.type in ("LAW", "BOUNTY", "PLEBISCITE", "BLUEPRINT", "WORLD_EVENT"):
                headlines.append(f"{ev.type}: {ev.params}")
        season_today = season_of(self.state.day)
        season_next = season_of(self.state.day + 1)
        forecast = list(self.state.event_forecast)
        self.state.gazette = {
            "day": yday,
            "headlines": headlines[:20],
            "market": self.state.stats.get("prices") if self.state.stats else {},
            "projects": [
                {"id": p.project_id, "status": p.status, "hours": p.delivered_hours, "need": p.need_hours}
                for p in self.state.projects.values() if p.status in ("pledging", "building")
            ],
            "alerts": [e.params.get("message") for e in self.state.events if e.type == "SETTLE_ERROR" and e.day == yday],
            "chronicle": [h for h in headlines if "入驻" in h or "违约" in h or "落成" in h or "当选" in h or "离开" in h],
            "pool": cents_to_coins(self.state.public_pool_cents, self.places),
            "population": len(self.agents.settlers()),
            "season_today": season_today,
            "season_next": season_next,
            "event_forecast": forecast,
            "stats": dict(self.state.stats),
        }


class TemplateLLM:
    """NPC 对话回退模板。真实 HTTP LLM 可替换 ctx.llm。"""

    def complete_text(self, constraints: dict) -> str:
        attitude = constraints.get("attitude", "normal")
        npc = constraints.get("name") or constraints.get("npc_id") or "老居民"
        words = constraints.get("traits") or ""
        topic = constraints.get("topic") or "镇子"
        if attitude == "warm":
            return f"{npc}笑着说：「{topic}上近来不错。{words}」"
        if attitude == "cold":
            return f"{npc}淡淡道：「嗯。」"
        return f"{npc}点点头：「关于{topic}，按规矩来就好。」"
