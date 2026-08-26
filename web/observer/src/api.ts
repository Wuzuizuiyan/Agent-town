export type Appearance = {
  skin: string;
  hair_style: string;
  hair_color: string;
  eyes: string;
  top: string;
  bottom: string;
  accessory: string;
};

export type Person = {
  id: string;
  kind: "settler" | "npc";
  name: string;
  vocation: string;
  appearance: Appearance;
  position: { x: number; y: number; region: string };
  facing: "n" | "e" | "s" | "w";
  activity: { action: string; label: string; started_tick: number };
  frozen: boolean;
  npc_id?: string;
  role?: string;
};

export type Snapshot = {
  tick: number;
  day: number;
  clock: { hour: number; speed: number; paused: boolean };
  map: {
    width: number;
    height: number;
    tiles: string;
    venues: { building_id?: string | null; kind: string; x: number; y: number; w: number; h: number; status: string }[];
    regions: Record<string, { x0: number; y0: number; x1: number; y1: number }>;
  };
  people: Person[];
  gazette: Record<string, unknown>;
  population: { settlers: number; npcs: number };
};

export type Catalog = {
  slots: Record<string, { id: string; label: string; layer: number; palette: string; npc_only: boolean }[]>;
  defaults: Appearance;
};

export type Envelope<T> = { ok: boolean; tick: number; day: number; data: T; error?: { code: string; message: string } };

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  const j = (await r.json()) as Envelope<T>;
  if (!j.ok) throw new Error(j.error?.message || "请求失败");
  return j.data;
}

export const api = {
  snapshot: () => get<Snapshot>("/v1/observer/snapshot"),
  catalog: () => get<Catalog>("/v1/observer/catalog"),
  chronicle: () => get<Record<string, unknown>[]>("/v1/observer/chronicle"),
  join: async (body: { name: string; vocation: string; appearance: Appearance }) => {
    const r = await fetch("/v1/observer/demo/join", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = (await r.json()) as Envelope<{ agent_id: string; person: Person }>;
    if (!j.ok) throw new Error(j.error?.message || "无法加入演示小镇");
    return j.data;
  },
};
