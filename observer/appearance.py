"""外观部件表：加载、缺省、入驻/PATCH 校验。不 import world，避免与内核循环依赖。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

SLOTS = ("skin", "hair_style", "hair_color", "eyes", "top", "bottom", "accessory")

DEFAULT_APPEARANCE = {
    "skin": "warm_2",
    "hair_style": "short",
    "hair_color": "ink",
    "eyes": "round",
    "top": "work_shirt",
    "bottom": "trousers",
    "accessory": "none",
}


class AppearanceError(ValueError):
    def __init__(self, message: str):
        self.code = "E1001"
        self.message = message
        super().__init__(message)


def _clean(name: str) -> str:
    return name.lstrip("\ufeff").strip()


def load_catalog(root: str | Path) -> dict[str, dict[str, dict[str, Any]]]:
    path = Path(root) / "config" / "外观部件表.csv"
    catalog: dict[str, dict[str, dict[str, Any]]] = {s: {} for s in SLOTS}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            slot = _clean(row.get("slot") or "")
            pid = _clean(row.get("part_id") or "")
            if slot not in catalog or not pid:
                continue
            catalog[slot][pid] = {
                "id": pid,
                "label": _clean(row.get("label") or pid),
                "layer": int(row.get("layer") or 0),
                "palette": _clean(row.get("palette") or ""),
                "npc_only": _clean(row.get("npc_only") or "0") in ("1", "true", "True"),
            }
    return catalog


def catalog_public(catalog: dict) -> dict:
    slots = {}
    for slot in SLOTS:
        slots[slot] = [
            {
                "id": p["id"],
                "label": p["label"],
                "layer": p["layer"],
                "palette": p["palette"],
                "npc_only": p["npc_only"],
            }
            for p in catalog[slot].values()
        ]
    return {"slots": slots, "defaults": dict(DEFAULT_APPEARANCE)}


def validate_appearance(
    raw: Any,
    catalog: dict,
    *,
    allow_npc_only: bool = False,
) -> dict[str, str]:
    if raw is None or raw == "":
        raw = {}
    if not isinstance(raw, dict):
        raise AppearanceError("外观必须是对象")
    out = dict(DEFAULT_APPEARANCE)
    for slot in SLOTS:
        if slot in raw and raw[slot] not in (None, ""):
            out[slot] = str(raw[slot]).strip()
    for slot in SLOTS:
        pid = out[slot]
        parts = catalog.get(slot) or {}
        if pid not in parts:
            raise AppearanceError(f"未知外观部件 {slot}={pid}")
        if parts[pid]["npc_only"] and not allow_npc_only:
            raise AppearanceError(f"外观部件仅 NPC 可用: {slot}={pid}")
    return out


def appearance_from_npc_row(row: dict[str, str], catalog: dict) -> dict[str, str]:
    raw = {slot: (row.get(slot) or "").strip() for slot in SLOTS}
    if not any(raw.values()):
        return dict(DEFAULT_APPEARANCE)
    return validate_appearance(raw, catalog, allow_npc_only=True)
