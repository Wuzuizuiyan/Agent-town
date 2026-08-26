import type { Appearance, Catalog } from "./api";

export const TILE = 16;
export const CW = 16;
export const CH = 24;

export const POSES = ["idle", "walk0", "walk1", "work", "eat", "sleep", "talk", "trade", "frozen"] as const;
export const DIRS = ["s", "w", "e", "n"] as const;

export const POSE_OF: Record<string, string> = {
  move: "walk",
  work: "work",
  contribute: "work",
  eat: "eat",
  sleep: "sleep",
  talk: "talk",
  intel_share: "talk",
  order_place: "trade",
  order_cancel: "trade",
  trade_private: "trade",
  trade_confirm: "trade",
  frozen: "frozen",
};

const TILE_CODE: Record<string, string> = {
  ".": "wild",
  w: "water",
  o: "well",
  H: "hall",
  f: "farm",
  F: "waste",
  t: "forest",
  T: "dense",
  m: "market",
  r: "home",
  R: "road",
};

const VENUE_TILE: Record<string, string> = {
  house: "house",
  warehouse: "warehouse",
  tavern: "tavern",
  bulletin: "bulletin",
  hall: "hall",
  well: "well",
};

type Atlas = {
  tile: number;
  tiles: { cols: number; order: string[]; map: Record<string, { x: number; y: number; i: number }> };
  chibi: {
    w: number;
    h: number;
    poses: string[];
    dirs: string[];
    skins: string[];
    hair_styles: string[];
    eyes: string[];
    tops: string[];
    bottoms: string[];
    accessories: string[];
  };
};

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("无法加载 " + src));
    img.src = src;
  });
}

export type Assets = {
  atlas: Atlas;
  tileset: HTMLImageElement;
  sheets: Record<string, HTMLImageElement>;
  hairBuf: HTMLCanvasElement;
};

export async function loadAssets(): Promise<Assets> {
  const atlas = (await fetch("/media/atlas.json").then((r) => r.json())) as Atlas;
  const [tileset, body, bottom, top, eyes, hair, acc] = await Promise.all(
    ["/media/tiles/tileset.png", "/media/chibi/body.png", "/media/chibi/bottom.png", "/media/chibi/top.png", "/media/chibi/eyes.png", "/media/chibi/hair.png", "/media/chibi/acc.png"].map(loadImage),
  );
  const hairBuf = document.createElement("canvas");
  hairBuf.width = CW;
  hairBuf.height = CH;
  return { atlas, tileset, sheets: { body, bottom, top, eyes, hair, acc }, hairBuf };
}

export function tileKind(code: string): string {
  return TILE_CODE[code] || "wild";
}

export function drawTile(ctx: CanvasRenderingContext2D, assets: Assets, kind: string, dx: number, dy: number, scale: number) {
  const info = assets.atlas.tiles.map[kind] || assets.atlas.tiles.map.wild;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(assets.tileset, info.x, info.y, TILE, TILE, dx, dy, TILE * scale, TILE * scale);
}

export function drawGround(ctx: CanvasRenderingContext2D, assets: Assets, tiles: string, scale: number, venues: { kind: string; x: number; y: number; w: number; h: number; status: string }[]) {
  ctx.imageSmoothingEnabled = false;
  for (let y = 0; y < 64; y++) {
    for (let x = 0; x < 64; x++) {
      drawTile(ctx, assets, tileKind(tiles[y * 64 + x] || "."), x * TILE * scale, y * TILE * scale, scale);
    }
  }
  for (const v of venues) {
    const kind = VENUE_TILE[v.kind];
    if (!kind || v.kind === "well") continue;
    for (let dy = 0; dy < v.h; dy++) {
      for (let dx = 0; dx < v.w; dx++) {
        drawTile(ctx, assets, v.status === "done" ? kind : "site", (v.x + dx) * TILE * scale, (v.y + dy) * TILE * scale, scale);
      }
    }
  }
}

function rowOf(list: string[], id: string, pose: string): number {
  const si = Math.max(0, list.indexOf(id));
  const pi = Math.max(0, POSES.indexOf(pose as (typeof POSES)[number]));
  return si * POSES.length + pi;
}

function dirCol(dir: string): number {
  const i = DIRS.indexOf(dir as (typeof DIRS)[number]);
  return i < 0 ? 0 : i;
}

function palette(catalog: Catalog | null, slot: string, id: string, fallback: string): string {
  const hit = catalog?.slots[slot]?.find((p) => p.id === id);
  return hit?.palette || fallback;
}

export function resolvePose(action: string, t: number): string {
  let pose = POSE_OF[action] || "idle";
  if (pose === "walk") pose = Math.floor(t / 220) % 2 === 0 ? "walk0" : "walk1";
  if (!(POSES as readonly string[]).includes(pose)) pose = "idle";
  return pose;
}

export function drawChibi(
  ctx: CanvasRenderingContext2D,
  assets: Assets,
  appearance: Appearance,
  action: string,
  dir: string,
  dx: number,
  dy: number,
  scale: number,
  t: number,
  catalog: Catalog | null,
) {
  const pose = resolvePose(action, t);
  const col = dirCol(dir);
  const ch = assets.atlas.chibi;
  const blit = (sheet: HTMLImageElement, list: string[], id: string) => {
    const row = rowOf(list, id, pose);
    ctx.drawImage(sheet, col * CW, row * CH, CW, CH, dx, dy, CW * scale, CH * scale);
  };
  ctx.imageSmoothingEnabled = false;
  blit(assets.sheets.body, ch.skins, appearance.skin);
  blit(assets.sheets.bottom, ch.bottoms, appearance.bottom);
  blit(assets.sheets.top, ch.tops, appearance.top);
  blit(assets.sheets.eyes, ch.eyes, appearance.eyes);

  const hair = assets.sheets.hair;
  const hctx = assets.hairBuf.getContext("2d")!;
  hctx.imageSmoothingEnabled = false;
  hctx.clearRect(0, 0, CW, CH);
  const hrow = rowOf(ch.hair_styles, appearance.hair_style, pose);
  hctx.drawImage(hair, col * CW, hrow * CH, CW, CH, 0, 0, CW, CH);
  hctx.globalCompositeOperation = "source-in";
  hctx.fillStyle = palette(catalog, "hair_color", appearance.hair_color, "#2a2420");
  hctx.fillRect(0, 0, CW, CH);
  hctx.globalCompositeOperation = "source-over";
  ctx.drawImage(assets.hairBuf, 0, 0, CW, CH, dx, dy, CW * scale, CH * scale);

  blit(assets.sheets.acc, ch.accessories, appearance.accessory);
}

export const REGION_CN: Record<string, string> = {
  farm: "农田",
  forest: "林地",
  town_hall: "公所",
  market: "市集",
  residential: "住宅区",
  well: "水源",
  wild: "空地",
};
