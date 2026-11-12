"""SRS voice check and test transmission (sortie/voice.py and its two API endpoints)."""
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sortie import config, voice
from sortie.db import Store
from sortie.mission import loadouts
from sortie.web.app import create_app


def _srs(tmp_path, sub="ExternalAudio"):
    root = tmp_path / "SRS"
    (root / sub).mkdir(parents=True, exist_ok=True)
    (root / sub / voice.EXE).write_bytes(b"MZ")
    return root


@pytest.fixture
def client(tmp_path):
    s = config.Settings(saved_games=str(tmp_path / "sg" / "DCS.openbeta"), dcs_install=str(tmp_path / "none"),
                        output_dir=str(tmp_path / "out"), db_path=str(tmp_path / "s.db"),
                        srs_path=str(tmp_path / "SRS"), srs_port=5002)
    app = create_app(s, settings_file=tmp_path / "settings.json", store=Store(s.db_path))
    loadouts.configure(None)
    c = TestClient(app)
    c.svc, c.tmp = app.state.svc, tmp_path
    return c


def test_audio_dir_finds_the_tool_in_either_layout(tmp_path):
    new = _srs(tmp_path / "new")                              # SRS 2.x: <SRS>\ExternalAudio
    assert voice.audio_dir(str(new)) == new / "ExternalAudio"
    assert voice.audio_dir(str(new) + "\\") == new / "ExternalAudio"
    assert voice.audio_dir(str(new / "ExternalAudio")) == new / "ExternalAudio"
    old = _srs(tmp_path / "old", sub="")                      # SRS 1.x: in the root
    assert voice.audio_dir(str(old)) == old
    gone = tmp_path / "gone"
    assert voice.audio_dir(str(gone)) == gone                 # unknown folder is passed through unchanged
    assert voice.exe_path(config.Settings(srs_path=str(gone))) is None


def test_check_lists_what_keeps_voice_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "server_listening", lambda port, *a, **k: False)
    monkeypatch.setattr(voice.sanitize, "installs", lambda s: [
        {"path": "E:\\DCS", "exists": True, "blocked": ["os", "io", "lfs"], "state": "sanitized"}])
    s = config.Settings(atc_enabled=True, voice="windows", srs_path=str(tmp_path / "nowhere"))
    c = voice.check(s)
    assert c["wanted"] and not c["ready"] and c["exe"] is None and c["server_up"] is False
    assert any(voice.EXE in p for p in c["problems"]) and any("sanitised" in p for p in c["problems"])
    assert c["blocked"] == [{"path": "E:\\DCS", "modules": ["os", "io"]}]
    warn = voice.warnings_for_mission(s)
    assert all(w.startswith("Voice: ") for w in warn) and any("SRS server" in w for w in warn)
    # everything in place: ready, and nothing to warn about
    monkeypatch.setattr(voice, "server_listening", lambda port, *a, **k: True)
    monkeypatch.setattr(voice.sanitize, "installs", lambda s: [
        {"path": "E:\\DCS", "exists": True, "blocked": [], "state": "desanitized"}])
    s = config.Settings(atc_enabled=True, voice="windows", srs_path=str(_srs(tmp_path)))
    c = voice.check(s)
    assert c["ready"] == voice.scripts.MOOSE_FILE.is_file() and c["exe"].endswith(voice.EXE)
    if c["ready"]:
        assert voice.warnings_for_mission(s) == []
    # voice not asked for: never warn
    assert voice.warnings_for_mission(config.Settings(srs_path=str(tmp_path / "nowhere"))) == []
    assert voice.warnings_for_mission(config.Settings(atc_enabled=True, voice="off")) == []


def test_command_matches_what_moose_sends(tmp_path):
    s = config.Settings(voice="windows", srs_path=str(_srs(tmp_path)), srs_port=5010)
    cmd = voice.command(s, "hello", [251.5, 251.0], coalition=1, label="Over lord!")
    assert cmd[0].endswith("ExternalAudio\\" + voice.EXE) or cmd[0].endswith("ExternalAudio/" + voice.EXE)
    assert cmd[1:] == ["-f", "251.5,251", "-m", "AM,AM", "-c", "1", "-p", "5010", "-n", "Overlord", "-v", "1.0",
                       "-l", "en-US", "--text=hello"]
    g = config.Settings(voice="google", google_credentials="C:\\g.json", srs_path=str(_srs(tmp_path)))
    assert voice.command(g, "x", [251.0])[-2:] == ["-G", "C:\\g.json"]
    with pytest.raises(FileNotFoundError):
        voice.command(config.Settings(srs_path=str(tmp_path / "nowhere")), "x", [251.0])


def test_speak_reports_each_failure_plainly(tmp_path, monkeypatch):
    missing = config.Settings(srs_path=str(tmp_path / "nowhere"))
    assert voice.speak(missing)["ok"] is False and voice.EXE in voice.speak(missing)["message"]
    s = config.Settings(voice="windows", srs_path=str(_srs(tmp_path)))
    monkeypatch.setattr(voice, "server_listening", lambda port, *a, **k: False)
    r = voice.speak(s)
    assert r["ok"] is False and "No SRS server" in r["message"]
    monkeypatch.setattr(voice, "server_listening", lambda port, *a, **k: True)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="x|INFO|Finished Sending Audio\n", stderr="")
    monkeypatch.setattr(voice.subprocess, "run", fake_run)
    r = voice.speak(s, 'say "this"  now', [305.0], coalition=1)
    assert r["ok"] is True and "305.000 MHz AM (red)" in r["message"]
    assert seen["cmd"][-1] == "--text=say 'this' now"         # quotes and runs of spaces cannot break the argument
    monkeypatch.setattr(voice.subprocess, "run", lambda cmd, **kw: SimpleNamespace(
        returncode=1, stdout="", stderr="Error: could not connect"))
    r = voice.speak(s)
    assert r["ok"] is False and "could not connect" in r["output"]

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(voice.subprocess, "run", slow)
    assert "in time" in voice.speak(s)["message"]


def test_voice_api(client, monkeypatch):
    v = client.get("/api/voice").json()
    assert v["wanted"] is False and v["exe"] is None and v["port"] == 5002
    assert client.post("/api/voice/test", json={"freq": 251.0}).json()["ok"] is False    # no tool: explained, not a 500
    assert client.post("/api/voice/test", json={"freq": 2.0}).status_code == 400
    assert client.post("/api/voice/test", json={"freq": 251.0, "coalition": 7}).status_code == 400
    _srs(client.tmp)
    client.put("/api/settings", json={"atc_enabled": True, "voice": "windows"})
    v = client.get("/api/voice").json()
    assert v["wanted"] is True and v["exe"].endswith(voice.EXE)
    monkeypatch.setattr(voice, "server_listening", lambda port, *a, **k: True)
    monkeypatch.setattr(voice.subprocess, "run", lambda cmd, **kw: SimpleNamespace(
        returncode=0, stdout="Finished Sending Audio", stderr=""))
    r = client.post("/api/voice/test", json={"freq": 251.0, "coalition": 2}).json()
    assert r["ok"] is True and "251.000" in r["message"]


def test_generated_mission_warns_when_voice_cannot_work(client, monkeypatch):
    cid = client.post("/api/campaigns", json={"theater_id": "gulf_crisis", "side": "blue", "squadron_id": "77fs",
                                              "callsign": "Rook", "seed": 5}).json()["id"]
    gen = client.post(f"/api/campaigns/{cid}/mission").json()
    assert not any(w.startswith("Voice:") for w in gen["warnings"])                      # voice off: silent
    client.put("/api/settings", json={"atc_enabled": True, "voice": "windows"})
    gen = client.post(f"/api/campaigns/{cid}/mission").json()
    assert any(w.startswith("Voice:") and voice.EXE in w for w in gen["warnings"])
