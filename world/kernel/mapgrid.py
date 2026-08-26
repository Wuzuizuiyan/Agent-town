"""64×64 地图、地理区域、占地与场所。move 属内核。"""

from __future__ import annotations

from world.kernel.errors import TownError
from world.kernel.state import WorldState

REGIONS = {
    "well": (0, 28, 7, 35),
    "town_hall": (26, 26, 37, 37),
    "farm": (8, 0, 31, 15),
    "forest": (32, 0, 55, 15),
    "market": (40, 28, 55, 43),
    "residential": (8, 40, 39, 63),
}

CN_REGION = {
    "水源": "well",
    "公所": "town_hall",
    "农田": "farm",
    "林地": "forest",
    "市集": "market",
    "住宅区": "residential",
    "空地": "wild",
    "酒馆": "market",
    "仓库": "market",
}


def iter_box(x0, y0, x1, y1):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            yield x, y


def region_at(x: int, y: int) -> str:
    for name, (x0, y0, x1, y1) in REGIONS.items():
        if x0 <= x <= x1 and y0 <= y <= y1:
            return name
    return "wild"


def bbox_tiles(x: int, y: int, w: int, h: int) -> list[tuple[int, int]]:
    out = []
    for dy in range(h):
        for dx in range(w):
            out.append((x + dx, y + dy))
    return out


def init_open_tiles(state: WorldState) -> None:
    farm = list(iter_box(*REGIONS["farm"]))
    farm.sort(key=lambda t: (-t[1], t[0]))
    state.open_farm = set(farm[:40])
    state.waste_farm = set(farm[40:])
    forest = list(iter_box(*REGIONS["forest"]))
    forest.sort(key=lambda t: (-t[1], t[0]))
    state.open_forest = set(forest[:40])
    state.dense_forest = set(forest[40:])


class MapService:
    def __init__(self, state: WorldState):
        self.state = state

    def region(self, x: int, y: int) -> str:
        return region_at(x, y)

    def enterable(self, x: int, y: int) -> bool:
        return 0 <= x <= 63 and 0 <= y <= 63

    def venue_at(self, x: int, y: int) -> dict | None:
        for b in self.state.buildings.values():
            tiles = bbox_tiles(b.x, b.y, b.w, b.h)
            if (x, y) in tiles and b.status in ("done", "building", "pledged"):
                return {
                    "building_id": b.building_id,
                    "kind": b.venue_kind,
                    "status": b.status,
                    "project": None,
                }
        for p in self.state.projects.values():
            if p.status in ("pledging", "building"):
                tiles = bbox_tiles(p.x, p.y, p.w, p.h)
                if (x, y) in tiles:
                    return {
                        "building_id": None,
                        "kind": p.venue_kind,
                        "status": p.status,
                        "project": p.project_id,
                    }
        return None

    def footprint_ok(self, x, y, w, h, allowed: list[str], kind: str) -> None:
        tiles = bbox_tiles(x, y, w, h)
        for tx, ty in tiles:
            if not self.enterable(tx, ty):
                raise TownError("E1026")
            reg = region_at(tx, ty)
            cn = {v: k for k, v in CN_REGION.items() if k in ("水源", "公所", "农田", "林地", "市集", "住宅区", "空地")}
            # allowed uses Chinese region names from CSV
            ok = False
            for a in allowed:
                a = a.strip()
                api = CN_REGION.get(a, a)
                if api == "wild":
                    if reg == "wild" or (a == "空地" and reg == "wild"):
                        ok = True
                elif api == reg:
                    ok = True
            if not ok:
                raise TownError("E1026")
        occupied = set()
        for b in self.state.buildings.values():
            if b.status == "wasted":
                continue
            occupied.update(bbox_tiles(b.x, b.y, b.w, b.h))
        for p in self.state.projects.values():
            if p.status in ("pledging", "building"):
                occupied.update(bbox_tiles(p.x, p.y, p.w, p.h))
        if occupied.intersection(tiles):
            raise TownError("E1026")
        if kind in ("house", "warehouse", "tavern", "bulletin", "hall") and any(
            t in self.state.open_farm or t in self.state.open_forest for t in tiles
        ):
            raise TownError("E1026")

    def manhattan_path(self, x0, y0, x1, y1) -> list[tuple[int, int]]:
        path = []
        x, y = x0, y0
        step = 1 if x1 >= x0 else -1
        while x != x1:
            x += step
            path.append((x, y))
        step = 1 if y1 >= y0 else -1
        while y != y1:
            y += step
            path.append((x, y))
        return path or [(x0, y0)]

    def all_road(self, path: list[tuple[int, int]]) -> bool:
        if not path:
            return False
        return all(p in self.state.roads for p in path)

    def occupants(self, region: str) -> list[str]:
        ids = []
        for a in self.state.agents.values():
            if region_at(a.x, a.y) == region:
                ids.append(a.npc_id or a.agent_id)
        return ids
