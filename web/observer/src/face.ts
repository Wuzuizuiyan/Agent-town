import { api, type Appearance, type Catalog } from "./api";
import { CH, CW, drawChibi, loadAssets, type Assets } from "./chibi";

const preview = document.getElementById("preview") as HTMLCanvasElement;
const slotsEl = document.getElementById("slots")!;
const jsonOut = document.getElementById("json-out")!;
const form = document.getElementById("face-form") as HTMLFormElement;
const nameEl = document.getElementById("name") as HTMLInputElement;
const vocEl = document.getElementById("vocation") as HTMLInputElement;

let assets: Assets;
let catalog: Catalog;
let appearance: Appearance;
let t0 = performance.now();

const SLOT_TITLE: Record<string, string> = {
  skin: "肤色",
  hair_style: "发型",
  hair_color: "发色",
  eyes: "眼睛",
  top: "上衣",
  bottom: "下装",
  accessory: "饰品",
};

function paint() {
  const ctx = preview.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = "#120d0a";
  ctx.fillRect(0, 0, preview.width, preview.height);
  const now = performance.now() - t0;
  const dirs = ["s", "w", "e", "n"] as const;
  dirs.forEach((d, i) => {
    const x = (i % 2) * 96 + 16;
    const y = Math.floor(i / 2) * 144 + 16;
    drawChibi(ctx, assets, appearance, "idle", d, x, y, 4, now, catalog);
  });
  jsonOut.textContent = JSON.stringify(appearance, null, 2);
}

function renderSlots() {
  slotsEl.innerHTML = "";
  for (const [slot, title] of Object.entries(SLOT_TITLE)) {
    const box = document.createElement("div");
    box.className = "slot-block";
    box.innerHTML = `<h3>${title}</h3>`;
    const chips = document.createElement("div");
    chips.className = "chips";
    for (const part of catalog.slots[slot] || []) {
      if (part.npc_only) continue;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = part.label;
      if (part.palette) {
        btn.style.borderBottom = `3px solid ${part.palette}`;
      }
      if (appearance[slot as keyof Appearance] === part.id) btn.classList.add("on");
      btn.addEventListener("click", () => {
        appearance = { ...appearance, [slot]: part.id };
        renderSlots();
        paint();
      });
      chips.appendChild(btn);
    }
    box.appendChild(chips);
    slotsEl.appendChild(box);
  }
}

document.getElementById("copy-json")!.addEventListener("click", async () => {
  await navigator.clipboard.writeText(JSON.stringify(appearance, null, 2));
  jsonOut.textContent = "已复制。\n" + JSON.stringify(appearance, null, 2);
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const data = await api.join({
      name: nameEl.value.trim() || "过客",
      vocation: vocEl.value.trim() || "旅人",
      appearance,
    });
    location.href = "/?id=" + encodeURIComponent(data.agent_id);
  } catch (err) {
    jsonOut.textContent = "加入失败：" + (err as Error).message + "\n请确认观测站以 TOWN_OBSERVER_DEMO=1 启动。";
  }
});

async function boot() {
  assets = await loadAssets();
  catalog = await api.catalog();
  appearance = { ...catalog.defaults };
  renderSlots();
  const loop = () => {
    paint();
    requestAnimationFrame(loop);
  };
  loop();
}

boot();
