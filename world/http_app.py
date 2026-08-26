"""HTTP /v1 接入（策划案第 4 章）。信封、鉴权、GM 属内核。"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from world.kernel.errors import TownError
from world.kernel.world import TownWorld

_WORLD: TownWorld | None = None


def get_world() -> TownWorld:
    global _WORLD
    if _WORLD is None:
        _WORLD = TownWorld(
            profile=os.environ.get("TOWN_PROFILE", "full"),
            gm_token=os.environ.get("TOWN_GM_TOKEN", "dev-gm-token"),
        )
    return _WORLD


def envelope_ok(world: TownWorld, data: Any) -> dict:
    return {"ok": True, "tick": world.state.tick, "day": world.state.day, "data": data}


def envelope_err(world: TownWorld, err: TownError) -> JSONResponse:
    status = 400
    if err.code == "E1014":
        status = 423
    if "鉴权" in (err.message or ""):
        status = 401
    body = {
        "ok": False,
        "tick": world.state.tick,
        "day": world.state.day,
        "error": {"code": err.code, "message": err.message},
    }
    return JSONResponse(status_code=status, content=body)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise TownError("E1001", "鉴权失败")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise TownError("E1001", "鉴权失败")
    return token


def create_app(world: TownWorld | None = None) -> FastAPI:
    app = FastAPI(title="Agent 小镇", version="0.16.0")
    w = world
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def town() -> TownWorld:
        return w if w is not None else get_world()

    @app.exception_handler(TownError)
    async def _town_error(_, exc: TownError):
        return envelope_err(town(), exc)

    @app.get("/v1/health")
    def health():
        t = town()
        return envelope_ok(t, {"paused": t.state.paused, "plugins": list(t.profile)})

    @app.post("/v1/owners/register")
    async def owners_register(request: Request):
        t = town()
        body = await _json(request)
        data = t.register_owner(body.get("invite_code"))
        return envelope_ok(t, data)

    @app.post("/v1/agents/register")
    async def agents_register(request: Request, authorization: str | None = Header(default=None)):
        t = town()
        kind, oid = t.auth(_bearer(authorization))
        if kind != "owner":
            raise TownError("E1001", "鉴权失败")
        body = await _json(request)
        card = {k: body.get(k) for k in (
            "name", "traits_words", "personality", "vocation", "backstory", "intro_npc", "trait"
        )}
        data = t.register_agent(oid, card, mode=body.get("mode") or "pull", webhook_url=body.get("webhook_url"))
        return envelope_ok(t, data)

    @app.post("/v1/agents/token/reissue")
    async def reissue(request: Request, authorization: str | None = Header(default=None)):
        t = town()
        kind, oid = t.auth(_bearer(authorization))
        if kind != "owner":
            raise TownError("E1001", "鉴权失败")
        body = await _json(request)
        data = t.reissue_agent_token(oid, body.get("agent_id") or "")
        return envelope_ok(t, data)

    @app.get("/v1/agents/{agent_id}/perception")
    def perception(agent_id: str, tick: int | None = Query(default=None),
                   authorization: str | None = Header(default=None)):
        t = town()
        kind, aid = t.auth(_bearer(authorization))
        if kind != "agent" or aid != agent_id:
            raise TownError("E1001", "鉴权失败")
        return envelope_ok(t, t.perception(agent_id, tick))

    @app.post("/v1/agents/{agent_id}/actions")
    async def actions(agent_id: str, request: Request, authorization: str | None = Header(default=None)):
        t = town()
        kind, aid = t.auth(_bearer(authorization))
        if kind != "agent" or aid != agent_id:
            raise TownError("E1001", "鉴权失败")
        body = await _json(request)
        if "tick" not in body or "seq" not in body or "action" not in body:
            raise TownError("E1001")
        data = t.submit_action(agent_id, int(body["tick"]), int(body["seq"]), body["action"], body.get("params") or {})
        return envelope_ok(t, data)

    @app.post("/v1/agents/{agent_id}/actions/callback")
    async def callback(agent_id: str, request: Request, authorization: str | None = Header(default=None)):
        return await actions(agent_id, request, authorization)

    @app.get("/v1/logs")
    def logs(day: int | None = Query(default=None), agent: str | None = Query(default=None),
             type: str | None = Query(default=None), authorization: str | None = Header(default=None)):
        t = town()
        kind, uid = t.auth(_bearer(authorization))
        if type == "CHRONICLE":
            rows = t.chronicle()
        else:
            rows = [t.log.as_dict(ev) for ev in t.state.events]
        if day is not None:
            rows = [r for r in rows if r.get("day") == day]
        if type and type != "CHRONICLE":
            rows = [r for r in rows if r.get("type") == type]
        if kind == "agent":
            rows = [r for r in rows if r.get("actor") == uid or type == "CHRONICLE"]
            if agent and agent != uid:
                raise TownError("E1001", "鉴权失败")
        elif agent:
            rows = [r for r in rows if r.get("actor") == agent]
        elif kind not in ("owner", "gm"):
            raise TownError("E1001", "鉴权失败")
        return envelope_ok(t, rows)

    @app.post("/v1/agents/{agent_id}/freeze")
    def freeze(agent_id: str, authorization: str | None = Header(default=None)):
        t = town()
        kind, oid = t.auth(_bearer(authorization))
        a = t.state.agents.get(agent_id)
        if kind != "owner" or not a or a.owner_id != oid:
            raise TownError("E1001", "鉴权失败")
        t.freeze_agent(agent_id)
        return envelope_ok(t, {"frozen": True})

    @app.post("/v1/agents/{agent_id}/unfreeze")
    def unfreeze(agent_id: str, authorization: str | None = Header(default=None)):
        t = town()
        kind, oid = t.auth(_bearer(authorization))
        a = t.state.agents.get(agent_id)
        if kind != "owner" or not a or a.owner_id != oid:
            raise TownError("E1001", "鉴权失败")
        t.unfreeze_agent(agent_id)
        return envelope_ok(t, {"frozen": False})

    @app.post("/v1/gm/speed")
    async def gm_speed(request: Request, authorization: str | None = Header(default=None)):
        t = town()
        _require_gm(t, authorization)
        body = await _json(request)
        if body.get("pause"):
            t.set_paused(True)
        else:
            t.set_speed(float(body.get("multiplier") or 1))
        return envelope_ok(t, {"speed": t.state.speed, "paused": t.state.paused})

    @app.post("/v1/gm/step")
    async def gm_step(request: Request, authorization: str | None = Header(default=None)):
        t = town()
        _require_gm(t, authorization)
        body = await _json(request)
        ticks = int(body.get("ticks") or 1)
        t.gm_step(ticks)
        return envelope_ok(t, {"tick": t.state.tick, "day": t.state.day})

    @app.post("/v1/gm/inject")
    async def gm_inject(request: Request, authorization: str | None = Header(default=None)):
        t = town()
        _require_gm(t, authorization)
        body = await _json(request)
        t.gm_inject(body.get("target") or "all", body.get("content") or "")
        return envelope_ok(t, {"injected": True})

    @app.post("/v1/gm/kick")
    async def gm_kick(request: Request, authorization: str | None = Header(default=None)):
        t = town()
        _require_gm(t, authorization)
        body = await _json(request)
        t.kick(body.get("agent_id") or "")
        return envelope_ok(t, {"kicked": True})

    @app.post("/v1/gm/blueprint")
    async def gm_blueprint(request: Request, authorization: str | None = Header(default=None)):
        t = town()
        _require_gm(t, authorization)
        body = await _json(request)
        data = t.gm_blueprint(body.get("blueprint_id") or "", body.get("decision") or "", body.get("footprint"))
        return envelope_ok(t, data)

    @app.post("/v1/gm/bounty")
    async def gm_bounty(request: Request, authorization: str | None = Header(default=None)):
        t = town()
        _require_gm(t, authorization)
        body = await _json(request)
        return envelope_ok(t, t.gm_bounty(body))

    @app.patch("/v1/agents/{agent_id}/appearance")
    async def patch_appearance(agent_id: str, request: Request, authorization: str | None = Header(default=None)):
        t = town()
        kind, oid = t.auth(_bearer(authorization))
        if kind != "owner":
            raise TownError("E1001", "鉴权失败")
        body = await _json(request)
        data = t.update_appearance(oid, agent_id, body.get("appearance") or body)
        return envelope_ok(t, {"appearance": data})

    @app.get("/v1/observer/snapshot")
    def observer_snapshot():
        t = town()
        from observer.snapshot import build_snapshot
        return envelope_ok(t, build_snapshot(t))

    @app.get("/v1/observer/catalog")
    def observer_catalog():
        t = town()
        from observer.appearance import catalog_public
        return envelope_ok(t, catalog_public(t.cfg.appearance))

    @app.get("/v1/observer/chronicle")
    def observer_chronicle(day: int | None = Query(default=None)):
        t = town()
        rows = t.chronicle()
        if day is not None:
            rows = [r for r in rows if r.get("day") == day]
        return envelope_ok(t, rows)

    @app.post("/v1/observer/demo/join")
    async def demo_join(request: Request):
        t = town()
        from observer.demo import join_demo
        body = await _json(request)
        return envelope_ok(t, join_demo(t, body))

    root = Path(__file__).resolve().parents[1]
    assets = root / "assets"
    dist = root / "web" / "observer" / "dist"
    if assets.is_dir():
        app.mount("/media", StaticFiles(directory=str(assets)), name="media")

    @app.get("/face")
    def face_page():
        p = dist / "face.html"
        if p.is_file():
            return FileResponse(p)
        return JSONResponse({"ok": False, "error": {"code": "E1001", "message": "请先构建 web/observer"}}, status_code=404)

    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="observer_web")

    return app


def _require_gm(world: TownWorld, authorization: str | None) -> None:
    kind, _ = world.auth(_bearer(authorization))
    if kind != "gm":
        raise TownError("E1001", "鉴权失败")


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


def push_webhooks(world: TownWorld) -> None:
    try:
        import httpx
    except ImportError:
        return
    for a in world.agents.settlers():
        if a.mode != "push" or not a.webhook_url:
            continue
        try:
            pack = world.perception(a.agent_id)
        except TownError:
            continue
        payload = {
            "ok": True,
            "tick": world.state.tick,
            "day": world.state.day,
            "deadline": "",
            "data": pack,
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        sig = hmac.new(a.token.encode(), raw, hashlib.sha256).hexdigest()
        try:
            r = httpx.post(
                a.webhook_url,
                content=raw,
                headers={"Content-Type": "application/json", "X-Town-Signature": f"sha256={sig}"},
                timeout=2.0,
            )
            if r.status_code >= 400:
                raise RuntimeError(r.status_code)
            a.webhook_fail = 0
        except Exception:
            a.webhook_fail += 1
            world.log.write("WEBHOOK_DOWN", actor=a.agent_id, params={"fail": a.webhook_fail})
            if a.webhook_fail >= world.cfg.i("webhook降级阈值", 5):
                a.mode = "pull"


def _clock_loop(world: TownWorld, stop: threading.Event) -> None:
    while not stop.is_set():
        if world.state.paused or world.state.stepping:
            stop.wait(0.05)
            continue
        try:
            world.begin_tick()
            if getattr(world, "observer_demo", False) or world.state.plugin_data.get("demo_seeded"):
                from observer.demo import drive_demo
                drive_demo(world)
            push_webhooks(world)
            seconds = world.cfg.f("tick现实秒数", 3600) / max(world.state.speed, 0.001)
            deadline = time.time() + max(0.05, seconds)
            while time.time() < deadline and not stop.is_set():
                if world.state.paused or world.state.stepping:
                    break
                time.sleep(0.05)
            if world.state.in_tick:
                world.end_tick()
        except TownError:
            stop.wait(0.2)
        except Exception:
            world.log.system("SETTLE_ERROR", "时钟循环异常")
            stop.wait(0.5)


def main() -> None:
    import uvicorn
    world = get_world()
    if os.environ.get("TOWN_OBSERVER_DEMO") == "1":
        from observer.demo import seed_demo
        seed_demo(world)
    app = create_app(world)
    stop = threading.Event()
    if os.environ.get("TOWN_NO_CLOCK") != "1":
        threading.Thread(target=_clock_loop, args=(world, stop), daemon=True).start()
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


app = create_app()
