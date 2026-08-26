from fastapi.testclient import TestClient

from world.http_app import create_app
from world.kernel.world import TownWorld

from tests.conftest import enroll


def test_http_register_perceive_act():
    w = TownWorld(profile="first_gun")
    app = create_app(w)
    client = TestClient(app)
    owner = client.post("/v1/owners/register", json={}).json()
    assert owner["ok"]
    token = owner["data"]["owner_token"]
    reg = client.post(
        "/v1/agents/register",
        json={
            "name": "王五",
            "traits_words": ["勤", "俭", "稳"],
            "vocation": "农夫",
            "backstory": "测试",
            "intro_npc": "npc_herald",
            "mode": "pull",
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert reg["ok"]
    aid = reg["data"]["agent_id"]
    atok = reg["data"]["agent_token"]
    w.state.agents[aid].x, w.state.agents[aid].y = 8, 15
    w.begin_tick()
    perc = client.get(
        f"/v1/agents/{aid}/perception",
        headers={"Authorization": f"Bearer {atok}"},
    ).json()
    assert perc["ok"]
    assert perc["data"]["self"]["agent_id"] == aid
    act = client.post(
        f"/v1/agents/{aid}/actions",
        json={"tick": w.state.tick, "seq": 1, "action": "work", "params": {}},
        headers={"Authorization": f"Bearer {atok}"},
    ).json()
    assert act["ok"] and act["data"]["accepted"]
    w.end_tick()
    gm = client.post(
        "/v1/gm/step",
        json={"ticks": 1},
        headers={"Authorization": "Bearer dev-gm-token"},
    ).json()
    assert gm["ok"]
    paused = client.post(
        "/v1/gm/speed",
        json={"pause": True},
        headers={"Authorization": "Bearer dev-gm-token"},
    ).json()
    assert paused["data"]["paused"] is True
    w.state.paused = False
    w.begin_tick()
    denied = client.post(
        f"/v1/agents/{aid}/actions",
        json={"tick": w.state.tick, "seq": 1, "action": "no_such", "params": {}},
        headers={"Authorization": f"Bearer {atok}"},
    )
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "E1001"
    w.end_tick()


def test_http_logs_chronicle():
    w = TownWorld(profile=["survival"])
    info = enroll(w)
    app = create_app(w)
    client = TestClient(app)
    rows = client.get(
        "/v1/logs?type=CHRONICLE",
        headers={"Authorization": f"Bearer {info['owner_token']}"},
    ).json()
    assert rows["ok"]
    assert any("入驻" in (r.get("chronicle") or "") for r in rows["data"])
