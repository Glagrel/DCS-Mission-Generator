import json

import pytest
from fastapi.testclient import TestClient

from sortie import config
from sortie.db import Store
from sortie.mission import loadouts
from sortie.runtime import simulate
from sortie.web.app import create_app


@pytest.fixture
def client(tmp_path):
    s = config.Settings(saved_games=str(tmp_path / "sg" / "DCS.openbeta"), dcs_install=str(tmp_path / "none"),
                        output_dir=str(tmp_path / "out"), db_path=str(tmp_path / "s.db"))
    app = create_app(s, settings_file=tmp_path / "settings.json", store=Store(s.db_path))
    loadouts.configure(None)
    c = TestClient(app)
    c.svc = app.state.svc
    c.tmp = tmp_path
    return c


def _new(client, **over):
    body = {"theater_id": "gulf_crisis", "side": "blue", "squadron_id": "77fs", "callsign": "Rook", "seed": 5}
    body.update(over)
    return client.post("/api/campaigns", json=body)


def test_static_pages_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Generate Next Mission" in r.text and "leaflet" in r.text.lower()
    for f in ("app.js", "pages.js", "mission.js", "style.css"):
        assert client.get(f"/static/{f}").status_code == 200


def test_status_and_theaters(client):
    s = client.get("/api/status").json()
    assert s["profile"] in ("light", "standard", "heavy") and s["ram_gb"] > 0 and "light" in s["profiles"]
    assert s["output_dir"].endswith("out") and s["terrains"]["PersianGulf"] is True
    th = client.get("/api/theaters").json()
    assert {t["id"] for t in th} >= {"coldwar_1985", "forager_1944", "gulf_crisis"}
    forager = next(t for t in th if t["id"] == "forager_1944")
    assert forager["terrain_fallback"] is True
    assert any(s["playable"] for s in forager["sides"]["blue"]["squadrons"])


def test_settings_roundtrip_and_validation(client):
    r = client.put("/api/settings", json={"profile": "heavy", "coop_slots": 2, "owned_modules": ["A-10C_2"],
                                          "voice": "windows", "atc_enabled": True})
    assert r.status_code == 200 and r.json()["profile"] == "heavy"
    assert json.loads((client.tmp / "settings.json").read_text())["owned_modules"] == ["A-10C_2"]
    assert client.get("/api/status").json()["profile"] == "heavy"
    mods = {m["id"]: m["owned"] for m in client.get("/api/modules").json()}
    assert mods["A-10C_2"] is True and mods["F-16C_50"] is False
    assert client.put("/api/settings", json={"profile": "ludicrous"}).status_code == 400
    assert client.put("/api/settings", json={"owned_modules": ["E-3A"]}).status_code == 400
    assert client.put("/api/settings", json={"coop_slots": 9}).status_code == 400
    assert client.put("/api/settings", json={"voice": "klingon"}).status_code == 400


def test_ownership_enforced_by_api(client):
    client.put("/api/settings", json={"owned_modules": ["A-10C_2"]})
    assert _new(client).status_code == 400                         # F-16C not owned
    assert _new(client, squadron_id="74fs").status_code == 200
    assert _new(client, theater_id="nope").status_code == 404


def test_full_loop_over_http(client):
    cid = _new(client).json()["id"]
    assert client.get("/api/campaigns").json()[0]["id"] == cid
    o = client.get(f"/api/campaigns/{cid}/overview").json()
    assert o["meta"]["turn"] == 1 and o["pilot"]["callsign"] == "Rook" and o["squadron"]["state"] == "ready"
    b = client.get(f"/api/campaigns/{cid}/briefing").json()
    assert b["assigned"] and b["reason"] and b["waypoints"]
    ato = client.get(f"/api/campaigns/{cid}/ato").json()
    assert ato["packages"] and all(p["reason"] for p in ato["packages"])
    assert sum(1 for p in ato["packages"] for f in p["flights"] if f["player"]) == 1
    m = client.get(f"/api/campaigns/{cid}/map").json()
    assert m["airbases"] and m["fronts"][0]["line"] and m["sams"] and m["routes"] and m["player_route"]
    assert client.get(f"/api/campaigns/{cid}/roster").json()[0]["is_player"]
    assert client.get(f"/api/campaigns/{cid}/logistics").json()["bases"]
    assert client.get(f"/api/campaigns/{cid}/career").json()["sorties"] == 0
    # debrief before flying is refused, with a useful message
    r = client.post(f"/api/campaigns/{cid}/debrief")
    assert r.status_code == 400
    client.svc.generate_mission(cid, with_moose=False)             # (HTTP route embeds MOOSE; tested below)
    st = client.svc.state(cid)
    ev = simulate.simulate(simulate.manifest_with_sides(st.sortie.summary["manifest"], st),
                           st.sortie.summary["sortie_id"], st.sortie.summary["player_group"])
    path = client.svc.events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in ev))
    live = client.get(f"/api/campaigns/{cid}/live").json()
    assert live["exists"] and live["count"] == len(ev) and live["events"]
    d = client.post(f"/api/campaigns/{cid}/debrief").json()
    assert d["turn"] == 1 and d["state"] == "flown" and d["next"]["turn"] == 2 and d["pilot"]["sorties"] == 1
    assert client.get(f"/api/campaigns/{cid}/debrief").json()["turn"] == 1
    assert client.get(f"/api/campaigns/{cid}/briefing").json()["turn"] == 2
    assert client.get(f"/api/campaigns/{cid}/history?kind=debrief").json()
    assert client.post(f"/api/campaigns/{cid}/skip").json()["state"] == "skipped"
    assert client.delete(f"/api/campaigns/{cid}").status_code == 200
    assert client.get(f"/api/campaigns/{cid}/overview").status_code == 400


def test_generate_endpoint_writes_miz_and_reports_path(client):
    cid = _new(client).json()["id"]
    r = client.post(f"/api/campaigns/{cid}/mission")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["filename"].endswith(".miz") and (client.tmp / "out" / body["filename"]).is_file()
    assert body["path"].startswith(str(client.tmp)) and body["stats"]["aircraft"] > 0


def test_generate_failure_is_reported(client):
    cid = _new(client).json()["id"]
    st = client.svc.state(cid)
    st.airbases["dhafra"].fuel.jet = 0                             # player's squadron grounded
    from sortie.state import save_state
    save_state(client.svc.store, cid, st)
    r = client.post(f"/api/campaigns/{cid}/mission")
    assert r.status_code == 400 and "standing down" in r.json()["detail"]
    assert not list((client.tmp / "out").glob("*.miz")) if (client.tmp / "out").exists() else True


def test_parallel_requests_do_not_collide(client):
    """The GUI fetches briefing and ATO at the same time; both trigger planning."""
    from concurrent.futures import ThreadPoolExecutor
    cid = _new(client).json()["id"]
    urls = [f"/api/campaigns/{cid}/{p}" for p in ("briefing", "ato", "map", "roster", "logistics", "overview")] * 4
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda u: client.get(u).status_code, urls))
    assert set(codes) == {200}
    assert len(client.svc.store.history(cid, "assignment")) == 1        # planned exactly once
