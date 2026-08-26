"""加载 config/ 六张 CSV。非法行保留旧值的热更在 World.reload_config。"""

from __future__ import annotations

import csv
from pathlib import Path


def _clean(name: str) -> str:
    return name.lstrip("\ufeff").strip()


class ConfigSnapshot:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.world: dict[str, str] = {}
        self.world_meta: dict[str, tuple[str, str]] = {}
        self.buildings: list[dict[str, str]] = []
        self.jobs: list[dict[str, str]] = []
        self.npcs: list[dict[str, str]] = []
        self.action_pre: dict[str, str] = {}
        self.traits: dict[str, dict[str, str]] = {}
        self.load()

    def load(self) -> None:
        cfg = self.root / "config"
        self.world, self.world_meta = self._kv(cfg / "世界参数表.csv")
        self.action_pre, _ = self._kv(cfg / "动作前置表.csv", key="前置项")
        self.buildings = self._rows(cfg / "建筑配置表.csv")
        self.jobs = self._rows(cfg / "岗位产出表.csv")
        self.npcs = self._rows(cfg / "NPC配置表.csv")
        traits = self._rows(cfg / "特质效果表.csv")
        self.traits = {}
        for row in traits:
            name = row.get("特质名", "")
            api = row.get("api_name", "")
            entry = dict(row)
            if name:
                self.traits[name] = entry
            if api:
                self.traits[api] = entry

    def _kv(self, path: Path, key: str = "参数名") -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
        data: dict[str, str] = {}
        meta: dict[str, tuple[str, str]] = {}
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = _clean(row.get(key) or row.get("参数名") or "")
                if not name or name.startswith("#"):
                    continue
                val = (row.get("值") or "").strip()
                unit = (row.get("单位") or "").strip()
                note = (row.get("说明") or "").strip()
                data[name] = val
                meta[name] = (unit, note)
        return data, meta

    def _rows(self, path: Path) -> list[dict[str, str]]:
        rows = []
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                first = _clean(next(iter(row.values())) or "")
                if not first or first.startswith("#"):
                    continue
                rows.append({_clean(k): (v or "").strip() for k, v in row.items() if k})
        return rows

    def f(self, key: str, default: float = 0.0) -> float:
        raw = self.world.get(key, self.action_pre.get(key))
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def i(self, key: str, default: int = 0) -> int:
        return int(self.f(key, default))

    def s(self, key: str, default: str = "") -> str:
        return self.world.get(key, self.action_pre.get(key, default)) or default

    def building(self, name_or_kind: str) -> dict[str, str] | None:
        for row in self.buildings:
            if row.get("建筑名称") == name_or_kind or row.get("场所键") == name_or_kind:
                return row
        return None

    def npc_by_id_or_name(self, key: str) -> dict[str, str] | None:
        for row in self.npcs:
            if row.get("npc_id") == key or row.get("NPC名") == key:
                return row
        return None

    def job(self, name: str) -> dict[str, str] | None:
        for row in self.jobs:
            if row.get("岗位") == name:
                return row
        return None

    def trait_mul(self, trait: str | None, param: str) -> float:
        if not trait:
            return 1.0
        row = self.traits.get(trait)
        if not row:
            return 1.0
        if row.get("作用参数") != param:
            return 1.0
        try:
            return float(row.get("乘算值") or 1)
        except ValueError:
            return 1.0

    def trait_api(self, trait: str | None) -> str | None:
        if not trait:
            return None
        row = self.traits.get(trait)
        if not row:
            return trait
        return row.get("api_name") or trait
