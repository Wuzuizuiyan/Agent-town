import { api, type Catalog, type Person, type Snapshot } from "./api";
import { CH, CW, REGION_CN, TILE, drawChibi, drawGround, loadAssets, type Assets } from "./chibi";

const canvas = document.getElementById("map") as HTMLCanvasElement;
const clockEl = document.getElementById("clock")!;
const popEl = document.getElementById("pop")!;
const cardEl = document.getElementById("card")!;
const gazetteEl = document.getElementById("gazette")!;
const chronicleEl = document.getElementById("chronicle")!;

let assets: Assets;
let catalog: Catalog;
let snap: Snapshot | null = null;
let prevPos = new Map<string, { x: number; y: number }>();
let lerpUntil = 0;
let selected: string | null = new URLSearchParams(location.search).get("id");
let cam = { x: 16 * TILE * 2, y: 14 * TILE * 2, zoom: 2 };
let dragging = false;
let last = { x: 0, y: 0 };
let ground: HTMLCanvasElement | null = null;
let groundKey = "";

function resize() {
  const wrap = canvas.parentElement!;
  canvas.width = wrap.clientWidth;
  canvas.height = wrap.clientHeight;
}

function rebuildGround() {
  if (!snap) return;
  const key = snap.map.tiles + snap.map.venues.map((v) => `${v.kind}${v.x}${v.y}${v.status}`).join();
  if (key === groundKey && ground) return;
  groundKey = key;
  ground = document.createElement("canvas");
  ground.width = 64 * TILE;
  ground.height = 64 * TILE;
  const g = ground.getContext("2d")!;
  drawGround(g, assets, snap.map.tiles, 1, snap.map.venues);
}

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function personScreen(p: Person, now: number): { x: number; y: number } {
  const cur = p.position;
  const prev = prevPos.get(p.id) || cur;
  const t = lerpUntil > now ? 1 - (lerpUntil - now) / 520 : 1;
  const e = t * t * (3 - 2 * t);
  return { x: lerp(prev.x, cur.x, e), y: lerp(prev.y, cur.y, e) };
}

function overlapShift(people: Person[], p: Person): { dx: number; dy: number } {
  const same = people.filter((o) => o.position.x === p.position.x && o.position.y === p.position.y);
  const i = same.findIndex((o) => o.id === p.id);
  return { dx: (i % 3) * 3 - 3, dy: Math.floor(i / 3) * 2 };
}

function drawBubble(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, on: boolean) {
  ctx.font = "10px Songti SC, STSong, serif";
  const w = Math.ceil(ctx.measureText(text).width) + 8;
  ctx.fillStyle = on ? "#d4ae62" : "#f3e6cf";
  ctx.strokeStyle = "#241c16";
  ctx.beginPath();
  ctx.roundRect(x - w / 2, y - 14, w, 12, 2);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#241c16";
  ctx.fillText(text, x - w / 2 + 4, y - 5);
}

function render(now: number) {
  const ctx = canvas.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = "#120d0a";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!snap || !ground) {
    requestAnimationFrame(render);
    return;
  }
  const z = cam.zoom;
  ctx.save();
  ctx.translate(-cam.x, -cam.y);
  ctx.scale(z, z);
  ctx.drawImage(ground, 0, 0);
  const people = [...snap.people].sort((a, b) => a.position.y - b.position.y || a.id.localeCompare(b.id));
  for (const p of people) {
    const pos = personScreen(p, now);
    const shift = overlapShift(snap.people, p);
    const px = pos.x * TILE + (TILE - CW) / 2 + shift.dx;
    const py = pos.y * TILE - (CH - TILE) + 2 + shift.dy;
    if (selected === p.id) {
      ctx.strokeStyle = "#d4ae62";
      ctx.strokeRect(px - 1, py - 1, CW + 2, CH + 2);
    }
    drawChibi(ctx, assets, p.appearance, p.activity.action, p.facing, px, py, 1, now, catalog);
    drawBubble(ctx, p.activity.label, px + CW / 2, py, selected === p.id);
  }
  ctx.restore();
  requestAnimationFrame(render);
}

function hitTest(mx: number, my: number): Person | null {
  if (!snap) return null;
  const now = performance.now();
  const wx = (mx + cam.x) / cam.zoom;
  const wy = (my + cam.y) / cam.zoom;
  let best: Person | null = null;
  let bestD = 18;
  for (const p of snap.people) {
    const pos = personScreen(p, now);
    const shift = overlapShift(snap.people, p);
    const px = pos.x * TILE + TILE / 2 + shift.dx;
    const py = pos.y * TILE - 4 + shift.dy;
    const d = Math.hypot(wx - px, wy - py);
    if (d < bestD) {
      best = p;
      bestD = d;
    }
  }
  return best;
}

function showCard(p: Person | null) {
  if (!p) {
    cardEl.classList.add("empty");
    cardEl.textContent = "地图上点一个小人";
    return;
  }
  cardEl.classList.remove("empty");
  const mini = document.createElement("canvas");
  mini.width = CW * 4;
  mini.height = CH * 4;
  drawChibi(mini.getContext("2d")!, assets, p.appearance, p.activity.action, p.facing, 0, 0, 4, performance.now(), catalog);
  cardEl.innerHTML = "";
  cardEl.appendChild(mini);
  const box = document.createElement("div");
  box.innerHTML = `<div class="who">${p.name}</div>
    ${p.kind === "npc" ? "老居民 · " + (p.role || p.vocation) : "定居者 · " + p.vocation}<br/>
    ${REGION_CN[p.position.region] || p.position.region} (${p.position.x}, ${p.position.y})<br/>
    正在：${p.activity.label}${p.frozen ? " · 冻结" : ""}`;
  cardEl.appendChild(box);
}

function fillLists(s: Snapshot, chronicle: Record<string, unknown>[]) {
  const g = s.gazette || {};
  const headlines = (g.headlines as string[]) || [];
  gazetteEl.innerHTML = headlines.length
    ? headlines.slice(0, 8).map((h) => `<li>${escapeHtml(h)}</li>`).join("")
    : "<li>今日尚无要事。拓居点刚醒来。</li>";
  const items = chronicle.slice(-8).reverse();
  chronicleEl.innerHTML = items.length
    ? items.map((r) => `<li>${escapeHtml(String(r.chronicle || ""))}</li>`).join("")
    : "<li>镇志还是空白页。</li>";
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

async function poll() {
  try {
    const next = await api.snapshot();
    if (snap && next.tick !== snap.tick) {
      prevPos = new Map(snap.people.map((p) => [p.id, { ...p.position }]));
      lerpUntil = performance.now() + 520;
    }
    snap = next;
    rebuildGround();
    clockEl.textContent = `第 ${next.day} 日 · 镇内 ${String(next.clock.hour).padStart(2, "0")} 时 · tick ${next.tick}${next.clock.paused ? " · 暂停" : ""}`;
    popEl.textContent = `定居 ${next.population.settlers} · 老居民 ${next.population.npcs}`;
    const sel = selected ? next.people.find((p) => p.id === selected) || null : null;
    if (sel) showCard(sel);
    const ch = await api.chronicle().catch(() => []);
    fillLists(next, ch);
  } catch (e) {
    clockEl.textContent = "观测中断：" + (e as Error).message;
  }
}

canvas.addEventListener("pointerdown", (e) => {
  dragging = true;
  last = { x: e.clientX, y: e.clientY };
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointerup", (e) => {
  const dx = Math.abs(e.clientX - last.x);
  const dy = Math.abs(e.clientY - last.y);
  dragging = false;
  if (dx + dy < 4) {
    const rect = canvas.getBoundingClientRect();
    const hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    selected = hit?.id || null;
    showCard(hit);
  }
});
canvas.addEventListener("pointermove", (e) => {
  if (!dragging) return;
  cam.x -= e.clientX - last.x;
  cam.y -= e.clientY - last.y;
  last = { x: e.clientX, y: e.clientY };
});
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const old = cam.zoom;
  cam.zoom = Math.max(2, Math.min(6, cam.zoom + (e.deltaY > 0 ? -1 : 1)));
  if (cam.zoom === old) return;
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const wx = (mx + cam.x) / old;
  const wy = (my + cam.y) / old;
  cam.x = wx * cam.zoom - mx;
  cam.y = wy * cam.zoom - my;
}, { passive: false });

window.addEventListener("resize", resize);

async function boot() {
  resize();
  assets = await loadAssets();
  catalog = await api.catalog();
  await poll();
  setInterval(poll, 1000);
  requestAnimationFrame(render);
}

boot();
