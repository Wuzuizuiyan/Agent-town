from fastapi.testclient import TestClient

from observer.appearance import AppearanceError, DEFAULT_APPEARANCE, load_catalog, validate_appearance
from observer.demo import join_demo, seed_demo
from observer.snapshot import build_snapshot, build_tile_string
from world.http_app import create_app
from world.kernel.errors import TownError
from world.kernel.world import TownWorld

from tests.conftest import enroll


from pathlib import Path


def test_art_atlas_exists():
    root = Path(__file__).resolve().parents[1]
    assert (root / "assets" / "atlas.json").is_file()
    assert (root / "assets" / "chibi" / "body.png").is_file()
    assert (root / "assets" / "tiles" / "tileset.png").is_file()


def test_catalog_loads_seven_slots():
    cat = load_catalog(".")
    for slot in DEFAULT_APPEARANCE:
        assert cat[slot], slot
    assert "guard_helm" in cat["accessory"]
    assert cat["accessory"]["guard_helm"]["npc_only"] is True


def test_validate_default_and_reject_unknown():
    cat = load_catalog(".")
    assert validate_appearance(None, cat) == DEFAULT_APPEARANCE
    try:
        validate_appearance({"skin": "nope"}, cat)
        assert False
    except AppearanceError as e:
        assert e.code == "E1001"
    try:
        validate_appearance({**DEFAULT_APPEARANCE, "accessory": "guard_helm"}, cat)
        assert False
    except AppearanceError as e:
        assert e.code == "E1001"
    ok = validate_appearance({**DEFAULT_APPEARANCE, "accessory": "guard_helm"}, cat, allow_npc_only=True)
    assert ok["accessory"] == "guard_helm"


def test_register_stores_appearance():
    w = TownWorld(profile="first_gun")
    owner = w.register_owner()
    info = w.register_agent(owner["owner_id"], {
        "name": "阿麦",
        "traits_words": ["稳", "肯", "干"],
        "vocation": "农夫",
        "backstory": "",
        "intro_npc": "npc_herald",
        "appearance": {**DEFAULT_APPEARANCE, "hair_style": "bob", "hair_color": "gold"},
    })
    ag = w.state.agents[info["agent_id"]]
    assert ag.appearance["hair_style"] == "bob"
    assert ag.appearance["hair_color"] == "gold"


def test_register_rejects_bad_appearance():
    w = TownWorld(profile="first_gun")
    owner = w.register_owner()
    try:
        w.register_agent(owner["owner_id"], {
            "name": "阿麦",
            "traits_words": ["稳", "肯", "干"],
            "vocation": "农夫",
            "backstory": "",
            "intro_npc": "npc_herald",
            "appearance": {"skin": "alien"},
        })
        assert False
    except TownError as e:
        assert e.code == "E1001"


def test_snapshot_contract_and_npc_faces():
    w = TownWorld(profile="full")
    snap = build_snapshot(w)
    assert len(snap["map"]["tiles"]) == 64 * 64
    assert snap["map"]["tiles"][31 * 64 + 3]  # well row-ish
    assert snap["population"]["npcs"] >= 7
    ids = {p["id"] for p in snap["people"]}
    for nid in ("npc_market", "npc_herald", "npc_guard", "npc_mayor", "npc_farmer", "npc_woodcutter", "npc_artisan"):
        assert nid in ids
    for p in snap["people"]:
        assert set(p["appearance"]) >= set(DEFAULT_APPEARANCE)
        assert 0 <= p["position"]["x"] <= 63
        assert 0 <= p["position"]["y"] <= 63
        assert p["activity"]["action"]
        assert p["activity"]["label"]
        assert p["facing"] in ("n", "e", "s", "w")
    tiles = build_tile_string(w.state)
    assert "o" in tiles and "f" in tiles and "H" in tiles


def test_observer_http_public_and_patch():
    w = TownWorld(profile="first_gun")
    info = enroll(w)
    app = create_app(w)
    c = TestClient(app)
    snap = c.get("/v1/observer/snapshot")
    assert snap.status_code == 200 and snap.json()["ok"]
    assert len(snap.json()["data"]["people"]) >= 1
    cat = c.get("/v1/observer/catalog").json()
    assert cat["ok"] and "skin" in cat["data"]["slots"]
    ch = c.get("/v1/observer/chronicle").json()
    assert ch["ok"]
    denied = c.post("/v1/observer/demo/join", json={"name": "甲", "vocation": "旅人"})
    assert denied.status_code == 423
    assert denied.json()["error"]["code"] == "E1014"
    patched = c.patch(
        f"/v1/agents/{info['agent_id']}/appearance",
        json={"appearance": {**DEFAULT_APPEARANCE, "top": "robe"}},
        headers={"Authorization": f"Bearer {info['owner_token']}"},
    )
    assert patched.json()["ok"]
    assert patched.json()["data"]["appearance"]["top"] == "robe"
    assert w.state.agents[info["agent_id"]].appearance["top"] == "robe"


def test_demo_seed_and_join_and_activity():
    w = TownWorld(profile="full")
    ids = seed_demo(w)
    assert len(ids) == 6
    w.begin_tick()
    from observer.demo import drive_demo
    drive_demo(w)
    snap = build_snapshot(w)
    names = {p["name"] for p in snap["people"]}
    assert {"禾苗", "木秋", "市川", "眠霜", "谈竹", "行路"} <= names
    frost = next(p for p in snap["people"] if p["name"] == "眠霜")
    assert frost["frozen"] is True
    assert frost["activity"]["action"] == "frozen"
    joined = join_demo(w, {
        "name": "观棋",
        "vocation": "旅人",
        "appearance": {**DEFAULT_APPEARANCE, "accessory": "flower"},
    })
    assert joined["person"]["appearance"]["accessory"] == "flower"
    w.end_tick()
    app = create_app(w)
    c = TestClient(app)
    r = c.post("/v1/observer/demo/join", json={
        "name": "第二人",
        "vocation": "工匠",
        "appearance": DEFAULT_APPEARANCE,
    })
    assert r.json()["ok"]
    people = c.get("/v1/observer/snapshot").json()["data"]["people"]
    assert any(p["name"] == "第二人" for p in people)
