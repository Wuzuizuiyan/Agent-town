"""程序生成 16px 地块与 16×24 纸娃娃图层。纯 Python PNG，无第三方依赖。

用法：python3 -m observer.art
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

TILE = 16
CW, CH = 16, 24
POSES = ["idle", "walk0", "walk1", "work", "eat", "sleep", "talk", "trade", "frozen"]
DIRS = ["s", "w", "e", "n"]

SKINS = {
    "pale": (240, 213, 196),
    "warm_1": (232, 184, 150),
    "warm_2": (212, 149, 106),
    "tan": (184, 116, 74),
    "deep": (107, 61, 42),
}
HAIR_STYLES = ["short", "short_bangs", "bob", "long", "bun", "messy", "bald"]
EYES = ["round", "narrow", "bright"]
TOPS = ["work_shirt", "vest", "robe", "apron", "coat", "tunic"]
BOTTOMS = ["trousers", "skirt", "shorts", "wrap"]
ACCESSORIES = ["none", "hat", "scarf", "glasses", "flower", "guard_helm"]

TOP_COLOR = {
    "work_shirt": (196, 122, 72),
    "vest": (78, 92, 64),
    "robe": (92, 58, 112),
    "apron": (232, 220, 196),
    "coat": (72, 84, 120),
    "tunic": (168, 96, 80),
}
BOTTOM_COLOR = {
    "trousers": (62, 54, 48),
    "skirt": (140, 72, 80),
    "shorts": (72, 88, 64),
    "wrap": (120, 86, 58),
}

INK = (38, 30, 26)
SHADE = (0, 0, 0)


def shade(rgb, k=0.72):
    return tuple(max(0, min(255, int(c * k))) for c in rgb)


def lite(rgb, k=1.18):
    return tuple(max(0, min(255, int(c * k))) for c in rgb)


class Pix:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.px = bytearray(w * h * 4)

    def put(self, x, y, rgb, a=255):
        if 0 <= x < self.w and 0 <= y < self.h and a:
            i = (y * self.w + x) * 4
            if a == 255 or self.px[i + 3] == 0:
                self.px[i:i + 4] = bytes((*rgb, a))
            else:
                oa = self.px[i + 3] / 255
                na = a / 255
                out = na + oa * (1 - na)
                if out <= 0:
                    return
                for k in range(3):
                    self.px[i + k] = int((rgb[k] * na + self.px[i + k] * oa * (1 - na)) / out)
                self.px[i + 3] = int(out * 255)

    def fill(self, rgb, a=255):
        for y in range(self.h):
            for x in range(self.w):
                self.put(x, y, rgb, a)

    def rect(self, x, y, w, h, rgb, a=255):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, rgb, a)

    def hline(self, x, y, w, rgb, a=255):
        self.rect(x, y, w, 1, rgb, a)

    def vline(self, x, y, h, rgb, a=255):
        self.rect(x, y, 1, h, rgb, a)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 4:(y + 1) * self.w * 4]) for y in range(self.h))
        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
        path.write_bytes(png)


def write_png(path: Path, pix: Pix):
    pix.save(path)


# --- tiles ---

TILE_ORDER = [
    ("wild", "空地"),
    ("water", "水源"),
    ("well", "水井"),
    ("hall", "公所"),
    ("farm", "农田"),
    ("waste", "荒地"),
    ("forest", "林地"),
    ("dense", "密林"),
    ("market", "市集"),
    ("home", "住宅区"),
    ("road", "道路"),
    ("house", "住宅"),
    ("warehouse", "仓库"),
    ("tavern", "酒馆"),
    ("bulletin", "公告栏"),
    ("site", "工地"),
]


def _noise(pix: Pix, seed: int, color, density=0.12, a=255):
    n = seed * 1103515245 + 12345
    for y in range(pix.h):
        for x in range(pix.w):
            n = (n * 1103515245 + 12345) & 0x7FFFFFFF
            if n / 0x7FFFFFFF < density:
                pix.put(x, y, color, a)


def draw_tile(kind: str) -> Pix:
    p = Pix(TILE, TILE)
    if kind == "wild":
        p.fill((92, 108, 64))
        _noise(p, 1, (110, 124, 72), 0.18)
        p.put(4, 9, (70, 88, 48))
        p.put(11, 3, (124, 136, 80))
    elif kind == "water":
        p.fill((58, 98, 132))
        p.rect(0, 6, 16, 2, (78, 128, 162))
        p.rect(3, 11, 8, 1, (160, 200, 214))
        _noise(p, 2, (46, 80, 112), 0.1)
    elif kind == "well":
        p.fill((58, 98, 132))
        p.rect(4, 4, 8, 8, (120, 116, 108))
        p.rect(5, 5, 6, 6, (40, 70, 96))
        p.rect(6, 6, 4, 4, (70, 120, 150))
        p.put(7, 7, (180, 210, 220))
        p.hline(4, 4, 8, INK)
        p.hline(4, 11, 8, INK)
    elif kind == "hall":
        p.fill((168, 140, 102))
        for i in range(0, 16, 4):
            p.vline(i, 0, 16, (148, 118, 84))
        p.hline(0, 8, 16, (128, 100, 72))
        _noise(p, 3, (184, 158, 118), 0.08)
    elif kind == "farm":
        p.fill((122, 96, 58))
        for y in (3, 7, 11):
            p.hline(1, y, 14, (86, 128, 54))
            p.hline(1, y + 1, 14, (70, 108, 44))
        p.put(5, 4, (210, 196, 90))
        p.put(10, 8, (210, 196, 90))
    elif kind == "waste":
        p.fill((138, 118, 78))
        _noise(p, 4, (120, 100, 64), 0.2)
        p.rect(6, 9, 3, 2, (96, 84, 52))
    elif kind == "forest":
        p.fill((58, 88, 48))
        _tree(p, 3, 2, (46, 92, 44))
        _tree(p, 9, 4, (36, 78, 36))
        p.rect(0, 14, 16, 2, (72, 56, 36))
    elif kind == "dense":
        p.fill((32, 54, 30))
        _tree(p, 1, 0, (28, 64, 32))
        _tree(p, 8, 1, (22, 52, 26))
        _tree(p, 4, 5, (36, 72, 38))
    elif kind == "market":
        p.fill((186, 150, 102))
        p.rect(1, 2, 14, 5, (196, 72, 58))
        p.rect(1, 2, 14, 1, (220, 120, 80))
        for x in range(1, 15, 2):
            p.vline(x, 2, 5, (160, 48, 40))
        p.rect(2, 8, 12, 6, (210, 186, 140))
        p.hline(2, 8, 12, INK)
    elif kind == "home":
        p.fill((110, 132, 78))
        _noise(p, 6, (126, 148, 90), 0.16)
        p.rect(0, 14, 16, 2, (168, 148, 112))
        p.hline(0, 13, 16, (148, 128, 92))
    elif kind == "road":
        p.fill((156, 132, 96))
        p.hline(0, 7, 16, (176, 156, 118))
        p.hline(0, 8, 16, (132, 110, 78))
        _noise(p, 7, (140, 118, 86), 0.12)
    elif kind == "house":
        p.fill((110, 132, 78))
        p.rect(2, 8, 12, 7, (186, 150, 110))
        p.rect(1, 3, 14, 6, (168, 72, 62))
        p.put(8, 2, (168, 72, 62))
        p.rect(7, 10, 3, 5, INK)
        p.put(4, 11, (210, 220, 230))
    elif kind == "warehouse":
        p.fill((186, 150, 102))
        p.rect(1, 5, 14, 10, (128, 108, 84))
        p.rect(1, 2, 14, 4, (96, 80, 62))
        p.rect(7, 9, 3, 6, INK)
        p.hline(3, 7, 10, (72, 60, 48))
    elif kind == "tavern":
        p.fill((186, 150, 102))
        p.rect(2, 6, 12, 9, (140, 78, 58))
        p.rect(1, 3, 14, 4, (92, 48, 40))
        p.rect(6, 10, 4, 5, INK)
        p.put(4, 9, (240, 200, 80))
    elif kind == "bulletin":
        p.fill((168, 140, 102))
        p.rect(4, 3, 8, 10, (196, 176, 140))
        p.rect(5, 4, 6, 8, (232, 220, 190))
        p.hline(5, 6, 6, (120, 80, 60))
        p.hline(5, 8, 4, (120, 80, 60))
        p.rect(7, 13, 2, 3, (96, 72, 48))
    else:  # site
        p.fill((138, 118, 78))
        p.rect(3, 8, 10, 5, (168, 140, 96))
        p.vline(4, 4, 8, (120, 88, 56))
        p.vline(11, 5, 7, (120, 88, 56))
        p.put(8, 6, (200, 160, 60))
    p.hline(0, 0, 16, shade((20, 16, 12), 1), 40)
    p.vline(0, 0, 16, shade((20, 16, 12), 1), 40)
    return p


def _tree(p: Pix, x, y, leaf):
    p.rect(x + 2, y + 8, 2, 5, (86, 62, 40))
    p.rect(x, y + 2, 6, 7, leaf)
    p.rect(x + 1, y, 4, 3, lite(leaf))
    p.put(x + 2, y + 3, shade(leaf))


def build_tileset(out: Path) -> dict:
    cols = 8
    rows = (len(TILE_ORDER) + cols - 1) // cols
    sheet = Pix(cols * TILE, rows * TILE)
    mapping = {}
    for i, (kind, _label) in enumerate(TILE_ORDER):
        tile = draw_tile(kind)
        cx, cy = (i % cols) * TILE, (i // cols) * TILE
        for y in range(TILE):
            for x in range(TILE):
                src = (y * TILE + x) * 4
                rgb = (tile.px[src], tile.px[src + 1], tile.px[src + 2])
                a = tile.px[src + 3]
                sheet.put(cx + x, cy + y, rgb, a)
        mapping[kind] = {"x": cx, "y": cy, "i": i}
        write_png(out / "tiles" / f"{kind}.png", tile)
    write_png(out / "tiles" / "tileset.png", sheet)
    return {"tile": TILE, "cols": cols, "order": [k for k, _ in TILE_ORDER], "map": mapping}


# --- chibi ---

def _flip(src: Pix) -> Pix:
    dst = Pix(src.w, src.h)
    for y in range(src.h):
        for x in range(src.w):
            i = (y * src.w + x) * 4
            if src.px[i + 3]:
                dst.put(src.w - 1 - x, y, (src.px[i], src.px[i + 1], src.px[i + 2]), src.px[i + 3])
    return dst


def _plot(p: Pix, pts, rgb, a=255):
    for x, y in pts:
        p.put(x, y, rgb, a)


def _head_pts(pose: str, facing: str):
    if pose == "sleep":
        return [(x, y) for x in range(2, 9) for y in range(10, 16)]
    if facing == "w":
        return [(x, y) for x in range(4, 10) for y in range(3, 10)]
    return [(x, y) for x in range(5, 11) for y in range(3, 10)]


def draw_body(pose: str, facing: str, skin) -> Pix:
    p = Pix(CW, CH)
    if facing == "e":
        return _flip(draw_body(pose, "w", skin))
    sk, dk = skin, shade(skin)
    sleeping = pose == "sleep"
    if sleeping:
        # 横躺
        p.rect(2, 12, 11, 5, sk)
        p.rect(2, 11, 7, 2, sk)
        p.rect(1, 12, 2, 4, dk)
        p.rect(11, 13, 3, 3, sk)  # feet
        return p
    # head
    p.rect(5, 3, 6, 6, sk)
    p.rect(6, 2, 4, 1, sk)
    p.rect(5, 9, 6, 1, dk)
    if facing == "n":
        p.rect(5, 3, 6, 6, dk)
        p.rect(6, 3, 4, 4, sk)
    # neck + torso
    p.rect(7, 9, 2, 2, sk)
    arm_y = 11
    if pose == "work":
        p.rect(3, 8, 3, 2, sk)  # raised arm
        p.rect(10, 11, 3, 2, sk)
    elif pose in ("talk", "trade"):
        p.rect(3, 10, 2, 3, sk)
        p.rect(11, 9, 2, 3, sk)
    elif pose == "eat":
        p.rect(4, 8, 2, 3, sk)
        p.rect(11, 11, 2, 3, sk)
    elif pose.startswith("walk"):
        off = 1 if pose == "walk1" else 0
        p.rect(4, 11 + off, 2, 3, sk)
        p.rect(10, 11 + (1 - off), 2, 3, sk)
    else:
        p.rect(4, 11, 2, 3, sk)
        p.rect(10, 11, 2, 3, sk)
    # legs / feet
    ly = 18
    if pose.startswith("walk"):
        if pose == "walk0":
            p.rect(6, ly, 2, 4, sk)
            p.rect(9, ly + 1, 2, 3, sk)
            p.rect(6, 22, 2, 1, dk)
            p.rect(9, 22, 2, 1, dk)
        else:
            p.rect(6, ly + 1, 2, 3, sk)
            p.rect(9, ly, 2, 4, sk)
            p.rect(6, 22, 2, 1, dk)
            p.rect(9, 22, 2, 1, dk)
    elif pose == "frozen":
        p.rect(6, ly, 2, 3, lite(sk, 1.1))
        p.rect(9, ly, 2, 3, lite(sk, 1.1))
    else:
        p.rect(6, ly, 2, 4, sk)
        p.rect(9, ly, 2, 4, sk)
        p.rect(6, 22, 2, 1, dk)
        p.rect(9, 22, 1 if facing == "w" else 2, 1, dk)
    return p


def draw_bottom(pose: str, facing: str, kind: str) -> Pix:
    p = Pix(CW, CH)
    if facing == "e":
        return _flip(draw_bottom(pose, "w", kind))
    c, d = BOTTOM_COLOR[kind], shade(BOTTOM_COLOR[kind])
    if pose == "sleep":
        if kind == "skirt":
            p.rect(7, 13, 6, 4, c)
        else:
            p.rect(8, 13, 5, 3, c)
        return p
    y0 = 15
    if kind == "skirt":
        p.rect(5, y0, 6, 2, c)
        p.rect(4, y0 + 2, 8, 3, c)
        p.hline(4, y0 + 4, 8, d)
    elif kind == "shorts":
        p.rect(6, y0, 4, 2, c)
        p.rect(5, y0 + 2, 3, 2, c)
        p.rect(8, y0 + 2, 3, 2, c)
    elif kind == "wrap":
        p.rect(5, y0, 6, 5, c)
        p.hline(5, y0, 6, lite(c))
    else:
        p.rect(6, y0, 2, 5, c)
        p.rect(9, y0, 2, 5, c)
        p.rect(6, y0, 5, 2, c)
        if pose.startswith("walk") and pose == "walk1":
            p.rect(6, y0 + 1, 2, 4, d)
    return p


def draw_top(pose: str, facing: str, kind: str) -> Pix:
    p = Pix(CW, CH)
    if facing == "e":
        return _flip(draw_top(pose, "w", kind))
    c, d = TOP_COLOR[kind], shade(TOP_COLOR[kind])
    if pose == "sleep":
        p.rect(4, 12, 7, 4, c)
        return p
    p.rect(5, 10, 6, 6, c)
    p.rect(5, 10, 6, 1, lite(c))
    if kind == "vest":
        p.rect(7, 11, 2, 4, d)
        p.vline(5, 10, 6, INK, 180)
        p.vline(10, 10, 6, INK, 180)
    elif kind == "robe":
        p.rect(4, 10, 8, 8, c)
        p.vline(8, 10, 8, d)
    elif kind == "apron":
        p.rect(6, 11, 4, 6, (232, 220, 196))
        p.hline(6, 11, 4, (180, 80, 70))
    elif kind == "coat":
        p.rect(4, 10, 8, 7, c)
        p.rect(4, 10, 2, 7, d)
        p.rect(10, 10, 2, 7, d)
    elif kind == "tunic":
        p.rect(5, 10, 6, 7, c)
    # sleeves follow arms
    if pose == "work":
        p.rect(3, 8, 3, 2, d)
    elif pose in ("talk", "trade", "eat"):
        p.rect(4, 10, 2, 2, d)
        p.rect(10, 10, 2, 2, d)
    else:
        p.rect(4, 11, 2, 2, d)
        p.rect(10, 11, 2, 2, d)
    return p


def draw_eyes(pose: str, facing: str, kind: str) -> Pix:
    p = Pix(CW, CH)
    if facing == "e":
        return _flip(draw_eyes(pose, "w", kind))
    if pose == "sleep" or facing == "n" or pose == "frozen":
        if pose == "sleep":
            p.hline(4, 13, 2, INK)
        elif pose == "frozen":
            p.hline(6, 6, 2, (80, 120, 180))
            p.hline(9, 6, 2, (80, 120, 180))
        return p
    if facing == "w":
        p.put(5, 6, INK)
        if kind == "bright":
            p.put(5, 6, (40, 40, 50))
            p.put(6, 6, (240, 240, 255), 200)
        return p
    if kind == "narrow":
        p.hline(6, 6, 2, INK)
        p.hline(9, 6, 2, INK)
    elif kind == "bright":
        p.put(6, 6, INK)
        p.put(7, 6, (250, 250, 255))
        p.put(9, 6, INK)
        p.put(10, 6, (250, 250, 255))
    else:
        p.put(6, 6, INK)
        p.put(7, 6, INK)
        p.put(9, 6, INK)
        p.put(10, 6, INK)
    return p


def draw_hair(pose: str, facing: str, kind: str) -> Pix:
    """白/灰图层，前端按发色着色。"""
    p = Pix(CW, CH)
    if facing == "e":
        return _flip(draw_hair(pose, "w", kind))
    w, g = (255, 255, 255), (188, 188, 188)
    if kind == "bald":
        if pose != "sleep":
            p.rect(6, 2, 4, 1, g, 120)
        return p
    if pose == "sleep":
        p.rect(2, 10, 7, 3, w)
        p.rect(1, 11, 2, 3, g)
        if kind == "long":
            p.rect(1, 13, 3, 4, w)
        return p
    # crown
    p.rect(5, 2, 6, 3, w)
    p.rect(4, 3, 8, 2, w)
    p.hline(5, 2, 6, g)
    if facing == "n":
        p.rect(4, 2, 8, 6, w)
        p.rect(5, 3, 6, 4, g)
    if kind == "short_bangs":
        p.rect(5, 4, 6, 2, w)
        p.hline(5, 5, 6, g)
    elif kind == "bob":
        p.rect(4, 6, 2, 4, w)
        p.rect(10, 6, 2, 4, w)
        p.rect(5, 8, 6, 2, w)
    elif kind == "long":
        p.rect(4, 6, 2, 8, w)
        p.rect(10, 6, 2, 8, w)
        p.rect(4, 13, 2, 4, g)
        p.rect(10, 13, 2, 4, g)
    elif kind == "bun":
        p.rect(6, 1, 4, 3, w)
        p.rect(7, 0, 2, 2, w)
        p.rect(6, 1, 4, 1, g)
    elif kind == "messy":
        p.put(4, 2, w)
        p.put(11, 2, w)
        p.put(3, 4, w)
        p.put(12, 5, w)
        p.rect(4, 3, 2, 3, w)
        p.rect(10, 3, 2, 3, w)
    # short: crown only
    if facing == "w":
        p.rect(4, 3, 3, 3, w)
    return p


def draw_acc(pose: str, facing: str, kind: str) -> Pix:
    p = Pix(CW, CH)
    if kind == "none":
        return p
    if facing == "e":
        return _flip(draw_acc(pose, "w", kind))
    if pose == "sleep":
        if kind == "flower":
            p.put(3, 10, (220, 90, 110))
        return p
    if kind == "hat":
        p.rect(3, 2, 10, 2, (196, 168, 92))
        p.rect(5, 0, 6, 3, (176, 140, 72))
        p.hline(3, 3, 10, shade((176, 140, 72)))
    elif kind == "scarf":
        p.rect(6, 9, 4, 2, (168, 64, 64))
        p.rect(10, 10, 2, 5, (168, 64, 64))
    elif kind == "glasses":
        if facing != "n":
            if facing == "w":
                p.put(5, 6, INK)
                p.hline(4, 6, 3, INK)
            else:
                p.rect(5, 6, 3, 2, INK, 180)
                p.rect(9, 6, 3, 2, INK, 180)
                p.hline(8, 6, 1, INK)
    elif kind == "flower":
        p.put(4, 3, (220, 90, 110))
        p.put(5, 2, (240, 140, 150))
        p.put(4, 2, (80, 140, 70))
    elif kind == "guard_helm":
        p.rect(4, 1, 8, 5, (96, 100, 108))
        p.rect(5, 2, 6, 3, (72, 76, 84))
        p.hline(4, 5, 8, (40, 42, 48))
        p.rect(4, 3, 2, 3, (96, 100, 108))
        p.rect(10, 3, 2, 3, (96, 100, 108))
    return p


def blit(dst: Pix, src: Pix, ox, oy):
    for y in range(src.h):
        for x in range(src.w):
            i = (y * src.w + x) * 4
            if src.px[i + 3]:
                dst.put(ox + x, oy + y, (src.px[i], src.px[i + 1], src.px[i + 2]), src.px[i + 3])


def pack_sheet(frames: list[tuple[str, str, Pix]], cols: int) -> Pix:
    n = len(frames)
    rows = (n + cols - 1) // cols
    sheet = Pix(cols * CW, rows * CH)
    for i, (_a, _b, pix) in enumerate(frames):
        blit(sheet, pix, (i % cols) * CW, (i // cols) * CH)
    return sheet


def build_chibi(out: Path) -> dict:
    chibi = out / "chibi"
    chibi.mkdir(parents=True, exist_ok=True)
    # body: skins × poses × dirs, 4 dirs as columns, rows = skin*poses
    body = Pix(len(DIRS) * CW, len(SKINS) * len(POSES) * CH)
    for si, (sname, srgb) in enumerate(SKINS.items()):
        for pi, pose in enumerate(POSES):
            for di, d in enumerate(DIRS):
                blit(body, draw_body(pose, d, srgb), di * CW, (si * len(POSES) + pi) * CH)
    write_png(chibi / "body.png", body)

    hair = Pix(len(DIRS) * CW, len(HAIR_STYLES) * len(POSES) * CH)
    for si, st in enumerate(HAIR_STYLES):
        for pi, pose in enumerate(POSES):
            for di, d in enumerate(DIRS):
                blit(hair, draw_hair(pose, d, st), di * CW, (si * len(POSES) + pi) * CH)
    write_png(chibi / "hair.png", hair)

    eyes = Pix(len(DIRS) * CW, len(EYES) * len(POSES) * CH)
    for si, st in enumerate(EYES):
        for pi, pose in enumerate(POSES):
            for di, d in enumerate(DIRS):
                blit(eyes, draw_eyes(pose, d, st), di * CW, (si * len(POSES) + pi) * CH)
    write_png(chibi / "eyes.png", eyes)

    top = Pix(len(DIRS) * CW, len(TOPS) * len(POSES) * CH)
    for si, st in enumerate(TOPS):
        for pi, pose in enumerate(POSES):
            for di, d in enumerate(DIRS):
                blit(top, draw_top(pose, d, st), di * CW, (si * len(POSES) + pi) * CH)
    write_png(chibi / "top.png", top)

    bottom = Pix(len(DIRS) * CW, len(BOTTOMS) * len(POSES) * CH)
    for si, st in enumerate(BOTTOMS):
        for pi, pose in enumerate(POSES):
            for di, d in enumerate(DIRS):
                blit(bottom, draw_bottom(pose, d, st), di * CW, (si * len(POSES) + pi) * CH)
    write_png(chibi / "bottom.png", bottom)

    acc = Pix(len(DIRS) * CW, len(ACCESSORIES) * len(POSES) * CH)
    for si, st in enumerate(ACCESSORIES):
        for pi, pose in enumerate(POSES):
            for di, d in enumerate(DIRS):
                blit(acc, draw_acc(pose, d, st), di * CW, (si * len(POSES) + pi) * CH)
    write_png(chibi / "acc.png", acc)

    return {
        "w": CW, "h": CH,
        "poses": POSES, "dirs": DIRS,
        "skins": list(SKINS),
        "hair_styles": HAIR_STYLES,
        "eyes": EYES, "tops": TOPS, "bottoms": BOTTOMS, "accessories": ACCESSORIES,
        "hair_tint": True,
    }


def build_ui(out: Path) -> None:
    banner = Pix(128, 32)
    banner.fill((44, 34, 28))
    for x in range(128):
        banner.put(x, 0, (212, 176, 108))
        banner.put(x, 31, (212, 176, 108))
    write_png(out / "ui" / "banner.png", banner)
    bubble = Pix(16, 16)
    bubble.rect(1, 1, 14, 10, (248, 240, 224))
    bubble.rect(0, 0, 16, 12, INK, 0)
    for x, y in [(0, 1), (15, 1), (0, 10), (15, 10)]:
        bubble.put(x, y, INK)
    bubble.rect(1, 1, 14, 1, INK)
    bubble.rect(1, 10, 14, 1, INK)
    bubble.vline(1, 1, 10, INK)
    bubble.vline(14, 1, 10, INK)
    bubble.put(6, 11, (248, 240, 224))
    bubble.put(7, 12, (248, 240, 224))
    write_png(out / "ui" / "bubble.png", bubble)


def generate(root: str | Path | None = None) -> Path:
    root = Path(root or Path(__file__).resolve().parents[1])
    out = root / "assets"
    tiles = build_tileset(out)
    chibi = build_chibi(out)
    build_ui(out)
    atlas = {
        "tile": TILE,
        "tiles": tiles,
        "chibi": chibi,
        "layers": ["body", "bottom", "top", "eyes", "hair", "acc"],
    }
    (out / "atlas.json").write_text(json.dumps(atlas, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main():
    out = generate()
    print(f"generated {out}")


if __name__ == "__main__":
    main()
