import os
import time

from sortie import config, paths


def _mk_sg(root, name, age):
    logs = root / name / "Logs"
    logs.mkdir(parents=True)
    f = logs / "dcs.log"
    f.write_text("x")
    t = time.time() - age
    os.utime(f, (t, t))


def test_saved_games_prefers_newest_log(tmp_path):
    _mk_sg(tmp_path, "DCS", 1000)
    _mk_sg(tmp_path, "DCS.openbeta", 10)
    (tmp_path / "DCS.openalpha").mkdir()
    assert paths.detect_saved_games(tmp_path).name == "DCS.openbeta"


def test_saved_games_fallback_without_logs(tmp_path):
    (tmp_path / "DCS").mkdir()
    assert paths.detect_saved_games(tmp_path).name == "DCS"
    assert paths.detect_saved_games(tmp_path / "nope") is None


def test_detect_install_common_path(tmp_path):
    inst = tmp_path / "Program Files" / "Eagle Dynamics" / "DCS World"
    (inst / "bin-mt").mkdir(parents=True)
    (inst / "bin-mt" / "DCS.exe").write_text("")
    assert paths.detect_install(roots=[tmp_path], use_registry=False) == inst
    assert paths.detect_install(roots=[tmp_path / "x"], use_registry=False) is None


def test_profile_by_ram():
    assert config.profile_for_ram(16) == "light"
    assert config.profile_for_ram(31.2) == "standard"
    assert config.profile_for_ram(64) == "heavy"


def test_profile_override_and_limits():
    s = config.Settings(profile="heavy")
    assert config.resolve_profile(s, ram_gb=8) == "heavy"
    s = config.Settings(profile="auto", overrides={"profiles": {"light": {"max_air": 5}}})
    assert config.resolve_profile(s, ram_gb=8) == "light"
    lim = config.profile_limits("light", s)
    assert lim["max_air"] == 5 and "bubble_km" in lim


def test_settings_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    s = config.Settings(owned_modules=["F-16C_50"], voice="windows")
    config.save_settings(s, p)
    assert config.load_settings(p).owned_modules == ["F-16C_50"]
    assert config.load_settings(tmp_path / "missing.json").profile == "auto"
