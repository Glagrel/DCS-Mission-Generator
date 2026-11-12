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


def test_coop_server_and_units_settings(client):
    srv = client.tmp / "sg" / "DCS.server1"
    r = client.put("/api/settings", json={"coop_slots": 2, "coop_extra_slots": 3, "coop_modules": ["A-10C_2"],
                                          "server_saved_games": str(srv), "save_to_server": True,
                                          "units": "metric"})
    assert r.status_code == 200
    s = client.get("/api/status").json()
    assert s["units"]["system"] == "metric" and s["units"]["alt"] == "m"
    assert s["server_output_dir"].endswith("SORTIE") and "DCS.server1" in s["server_output_dir"]
    assert len(s["event_files"]) >= 2 and "DCS.server1" in s["event_files"][1]
    assert client.put("/api/settings", json={"units": "furlongs"}).status_code == 400
    assert client.put("/api/settings", json={"coop_extra_slots": 99}).status_code == 400
    assert client.put("/api/settings", json={"coop_modules": ["E-3A"]}).status_code == 400
    client.put("/api/settings", json={"coop_modules": None})
    cid = _new(client).json()["id"]
    b = client.get(f"/api/campaigns/{cid}/briefing").json()
    assert b["units"] == "metric" and b["waypoints"][1]["alt"].endswith(" m") and b["mission_start"]
    body = client.post(f"/api/campaigns/{cid}/mission").json()
    assert body["extra_paths"] and (srv / "Missions" / "SORTIE" / body["filename"]).is_file()
    assert sum(x["seats"] for x in body["slots"]) == 5 and body["stats"]["kneeboard_pages"] >= 2
    assert client.put("/api/settings", json={"server_saved_games": ""}).json()["server_saved_games"] is None


def test_unhandled_errors_are_reported_with_detail(client, monkeypatch):
    from fastapi.testclient import TestClient
    cid = _new(client).json()["id"]
    monkeypatch.setattr(client.svc, "poll_live", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    quiet = TestClient(client.app, raise_server_exceptions=False)
    r = quiet.get(f"/api/campaigns/{cid}/live")
    assert r.status_code == 500 and "RuntimeError: boom" in r.json()["detail"] and "sortie.log" in r.json()["detail"]
    assert client.get("/api/status").json()["restart_needed"] is False


def test_restart_needed_when_code_changes(client, monkeypatch):
    from sortie.web import app as webapp
    real = webapp.code_stamp()
    monkeypatch.setattr(webapp, "code_stamp", lambda: real + 60)
    assert client.get("/api/status").json()["restart_needed"] is True


# ---- desanitize button ------------------------------------------------------------------------------
SANITIZED = """do
\tsanitizeModule('os')
\tsanitizeModule('io')
\tsanitizeModule('lfs')
\t_G['require'] = nil
end
"""


def _fake_install(root, text=SANITIZED):
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "DCS.exe").write_text("")
    (root / "Scripts").mkdir()
    (root / "Scripts" / "MissionScripting.lua").write_text(text)
    return root


def test_sanitize_status_parsing(tmp_path):
    from sortie import sanitize
    inst = _fake_install(tmp_path / "A")
    assert sanitize.status(inst)["state"] == "sanitized" and sanitize.status(inst)["blocked"] == ["os", "io", "lfs"]
    (inst / "Scripts" / "MissionScripting.lua").write_text(
        "do\n\t-- SORTIE desanitize: sanitizeModule('os')\n\t--sanitizeModule('io')\n\t-- sanitizeModule('lfs')\nend\n")
    assert sanitize.status(inst)["state"] == "desanitized"
    (inst / "Scripts" / "MissionScripting.lua").write_text("do\n\tsanitizeModule('os')\n\t--sanitizeModule('io')\n\t--sanitizeModule('lfs')\nend\n")
    assert sanitize.status(inst)["state"] == "desanitized"          # os alone does not block the event file
    assert sanitize.status(tmp_path / "nowhere")["state"] == "missing"
    log = tmp_path / "dcs.log"
    log.write_text('2026 INFO APP (Main): Command line: "E:\\Program Files\\DCS World\\bin/DCS.exe"  --server -w DCS.server1\n')
    assert str(sanitize.install_from_log(log)) == "E:\\Program Files\\DCS World"
    assert sanitize.install_from_log(tmp_path / "missing.log") is None


def test_desanitize_and_restore_through_the_api(client):
    import shutil
    if not (shutil.which("powershell") or shutil.which("pwsh")):
        pytest.skip("PowerShell not available")
    inst = _fake_install(client.tmp / "FakeDCS")
    client.put("/api/settings", json={"dcs_install": str(inst)})
    rows = client.get("/api/desanitize").json()
    assert len(rows) == 1 and rows[0]["state"] == "sanitized" and rows[0]["uses"] == ["game"]
    cid = _new(client).json()["id"]
    gen = client.post(f"/api/campaigns/{cid}/mission").json()
    assert [i["path"] for i in gen["sanitized"]] == [str(inst)]      # this is what triggers the pop-up
    r = client.post("/api/desanitize", json={"path": str(inst), "action": "desanitize"})
    assert r.status_code == 200 and r.json()["state"] == "desanitized" and r.json()["backup"] is True
    text = (inst / "Scripts" / "MissionScripting.lua").read_text()
    assert "-- SORTIE desanitize: sanitizeModule('io')" in text and "_G['require'] = nil" in text
    assert client.get("/api/desanitize").json()[0]["state"] == "desanitized"
    assert client.post(f"/api/campaigns/{cid}/mission").json()["sanitized"] == []    # no pop-up any more
    r = client.post("/api/desanitize", json={"path": str(inst), "action": "restore"})
    assert r.status_code == 200 and r.json()["state"] == "sanitized"
    assert (inst / "Scripts" / "MissionScripting.lua").read_text().replace("\r\n", "\n") == SANITIZED


def test_desanitize_api_only_touches_detected_installs(client):
    other = _fake_install(client.tmp / "Other")
    r = client.post("/api/desanitize", json={"path": str(other), "action": "desanitize"})
    assert r.status_code == 400 and "not a detected DCS install" in r.json()["detail"]
    assert (other / "Scripts" / "MissionScripting.lua").read_text() == SANITIZED
    inst = _fake_install(client.tmp / "Mine")
    client.put("/api/settings", json={"dcs_install": str(inst)})
    assert client.post("/api/desanitize", json={"path": str(inst), "action": "format"}).status_code == 400
