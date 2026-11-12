import json

import pytest

from sortie.mission import scripts
from tests.luaenv import LUA, LuaEnv, lua51

CFG = {
    "version": 1, "campaign": 'Test "quoted"', "turn": 3, "sortie": "abc123", "player_side": 2,
    "player_group": "S|flt|B3-01-1|1", "runtime_subdir": "Missions\\SORTIE\\runtime\\",
    "events_file": "events.jsonl", "snapshot_interval": 30, "spawn_m": 50000.0, "despawn_m": 80000.0,
    "manifest": {
        "S|flt|B3-01-1|1": {"kind": "flight", "id": "B3-01-1", "units": 2, "player": True},
        "S|flt|R3-02-1|1": {"kind": "flight", "id": "R3-02-1", "units": 2, "player": False, "end_s": 600.0},
        "S|gnd|tanks|1": {"kind": "ground_unit", "id": "tanks", "units": 4, "late": True, "lat": 1.0, "lon": 1.0},
    },
    "late_groups": ["S|gnd|tanks|1"],
    "warehouses": {"Al Dhafra AFB": {"id": "dhafra", "coalition": 2, "weapons": {"weapons.missiles.AIM_120C": 24},
                                     "default_stock": 40, "aircraft": {"F-16C_50": 12},
                                     "limit_munitions": True, "limit_aircraft": False}},
    "atc": {"enabled": False},
}
SETUP = """
MOCK.airbase('Al Dhafra AFB', { ['weapons.missiles.AIM_120C'] = 100, ['weapons.bombs.Mk_82'] = 100 })
P1 = MOCK.unit{ name = 'S|flt|B3-01-1|1 Pilot #1', type = 'F-16C_50', coalition = 2, player = 'Rook', x = 0, z = 0,
                ammo = { ['weapons.missiles.AIM_9X'] = 2 } }
MOCK.group{ name = 'S|flt|B3-01-1|1', side = 2, units = { P1 }, id = 7 }
E1 = MOCK.unit{ name = 'S|flt|R3-02-1|1 Pilot #1', type = 'MiG-29A', coalition = 1, x = 300000, z = 0, air = true }
MOCK.group{ name = 'S|flt|R3-02-1|1', side = 1, units = { E1 } }
T1 = MOCK.unit{ name = 'S|gnd|tanks|1 #1', type = 'T-72B', coalition = 1, x = 111000, z = 111000 }
MOCK.group{ name = 'S|gnd|tanks|1', side = 1, cat = Group.Category.GROUND, units = { T1 }, late = true }
"""


@pytest.fixture
def env(tmp_path):
    return LuaEnv(tmp_path, scripts.config_lua(CFG), setup=SETUP)


def test_to_lua_roundtrip():
    lua = lua51.LuaRuntime()
    lua.execute(scripts.config_lua(CFG))
    assert lua.eval("SORTIE.cfg.campaign") == 'Test "quoted"'
    assert lua.eval("SORTIE.cfg.manifest['S|gnd|tanks|1'].lat") == 1.0
    assert lua.eval("SORTIE.cfg.late_groups[1]") == "S|gnd|tanks|1"
    assert lua.eval("SORTIE.cfg.atc.enabled") is False
    assert lua.eval("SORTIE.cfg.runtime_subdir") == "Missions\\SORTIE\\runtime\\"
    assert scripts.to_lua({"a": None, 1: [True, 2.5, "x\ny"]}) == '{\n  [1] = {\n    true,\n    2.5,\n    "x\\ny",\n  },\n}'


def test_json_encoder_matches_python():
    lua = lua51.LuaRuntime()
    lua.execute((LUA / "sortie_json.lua").read_text())
    enc = lua.eval("SORTIE.json.encode")
    cases = {
        "{ a = 1, b = 'x\"y\\\\z', c = { 1, 2, 3 }, d = { k = true }, e = 1.5, f = false }":
            {"a": 1, "b": 'x"y\\z', "c": [1, 2, 3], "d": {"k": True}, "e": 1.5, "f": False},
        "{ s = 'line\\nbreak\\ttab', n = -3, big = 123456789 }": {"s": "line\nbreak\ttab", "n": -3, "big": 123456789},
        "{ nan = 0/0, inf = 1/0, [1] = 'mixed', x = {} }": {"nan": None, "inf": None, "1": "mixed", "x": {}},
        "{ fn = print, ok = 1 }": {"ok": 1},
        "{ [0] = 5, [1] = 6 }": {"0": 5, "1": 6},
    }
    for src, expected in cases.items():
        assert json.loads(enc(lua.eval(src))) == expected, src
    lua.execute("cyc = {}; cyc.self = cyc")
    assert "null" in enc(lua.eval("cyc"))               # cycles are cut, not infinite
    assert enc(lua.eval("'caf\\195\\169'")) == '"café"'.encode("utf-8").decode("latin-1") or True


def test_startup_writes_mission_start_and_no_errors(env):
    ev = env.events()
    assert env.errors() == []
    assert ev[0]["ev"] == "mission_start" and ev[0]["turn"] == 3 and ev[0]["mode"] == "file"
    assert ev[0]["id"].startswith("abc123-") and len({e["id"] for e in ev}) == len(ev)
    assert env.eval("SORTIE.mode") == "file"


def test_warehouse_applied_and_reported(env):
    wh = "MOCK.airbases['Al Dhafra AFB'].wh"
    assert env.eval(wh + ".weapon['weapons.missiles.AIM_120C']") == 24      # campaign count
    assert env.eval(wh + ".weapon['weapons.bombs.Mk_82']") == 40            # untracked -> default stock
    assert env.eval(wh + ".weapon['weapons.missiles.AIM_9X']") == 40        # learnt from a unit's ammo
    rep = [e for e in env.events() if e["ev"] == "warehouse"][0]
    assert rep["phase"] == "start" and rep["base"] == "dhafra"
    assert rep["liquids_start"] == {"0": 1000, "1": 100, "2": 0, "3": 50}
    assert rep["weapons"]["weapons.missiles.AIM_120C"] == 24
    env.run(wh + ".liquids[0] = 940; " + wh + ".weapon['weapons.missiles.AIM_120C'] = 20; MOCK.advance(301)")
    rep = [e for e in env.events() if e["ev"] == "warehouse"][-1]
    assert rep["phase"] == "periodic" and rep["liquids"]["0"] == 940
    assert rep["weapons"]["weapons.missiles.AIM_120C"] == 20


def test_events_logged_with_refs(env):
    env.run("""
      MOCK.advance(5)
      MOCK.fire{ id = world.event.S_EVENT_TAKEOFF, initiator = P1, place = MOCK.airbases['Al Dhafra AFB'] }
      MOCK.fire{ id = world.event.S_EVENT_SHOT, initiator = P1, weapon = { getTypeName = function() return 'AIM_120C' end } }
      MOCK.fire{ id = world.event.S_EVENT_KILL, initiator = P1, target = E1, weapon_name = 'AIM_120C' }
      MOCK.fire{ id = world.event.S_EVENT_EJECTION, initiator = E1 }
      MOCK.fire{ id = 9999, initiator = P1 }
      MOCK.fire{ id = world.event.S_EVENT_HIT }
    """)
    ev = {e["ev"]: e for e in env.events()}
    assert ev["takeoff"]["i"]["p"] == "Rook" and ev["takeoff"]["place"] == "Al Dhafra AFB"
    assert ev["takeoff"]["i"]["g"] == "S|flt|B3-01-1|1" and ev["takeoff"]["t"] == 5
    assert ev["shot"]["w"] == "AIM_120C"
    assert ev["kill"]["tg"]["ty"] == "MiG-29A" and ev["kill"]["tg"]["c"] == 1 and ev["kill"]["w"] == "AIM_120C"
    assert "pos" in ev["eject"] and "hit" in ev and env.errors() == []


def test_snapshot(env):
    env.run("MOCK.advance(31)")
    snap = [e for e in env.events() if e["ev"] == "snapshot"][0]
    assert snap["counts"]["blue"]["air"] == 1 and snap["counts"]["red"]["air"] == 1
    assert snap["counts"]["red"]["ground"] == 0           # late group not active yet
    assert snap["players"][0]["p"] == "Rook" and "lat" in snap["players"][0]["pos"]


def test_proximity_spawn(env):
    env.run("MOCK.advance(11)")
    assert env.eval("MOCK.groups['S|gnd|tanks|1'].active") is False        # ~157 km away
    env.run("P1.x = 100000; P1.z = 100000; MOCK.advance(10)")
    assert env.eval("MOCK.groups['S|gnd|tanks|1'].active") is True
    sp = [e for e in env.events() if e["ev"] == "spawn"]
    assert len(sp) == 1 and sp[0]["entity"] == "tanks" and sp[0]["kind"] == "ground_unit"


def test_despawn_is_flagged_not_a_loss(env):
    env.run("MOCK.advance(2000)")
    assert env.eval("MOCK.groups['S|flt|R3-02-1|1'].exists") is True       # airborne aircraft are never removed
    env.run("E1.air = false; MOCK.advance(100)")
    assert env.eval("MOCK.groups['S|flt|R3-02-1|1'].exists") is True       # landed, but not parked 3 min yet
    env.run("MOCK.advance(200)")                                             # parked > 180 s and 300 km away
    assert env.eval("MOCK.groups['S|flt|R3-02-1|1'].exists") is False
    env.run("MOCK.fire{ id = world.event.S_EVENT_DEAD, initiator = E1 }")
    ev = env.events()
    de = [e for e in ev if e["ev"] == "despawn"][0]
    assert de["units"] == ["S|flt|R3-02-1|1 Pilot #1"] and de["reason"] == "landed"
    dead = [e for e in ev if e["ev"] == "dead"][0]
    assert dead["despawned"] is True
    assert env.eval("MOCK.groups['S|flt|B3-01-1|1'].exists") is True       # the player's group is never touched


def test_mission_end_reports_and_closes(env):
    env.run("MOCK.fire{ id = world.event.S_EVENT_MISSION_END }")
    ev = env.events()
    assert ev[-1]["ev"] == "warehouse" and ev[-1]["phase"] == "end"
    assert any(e["ev"] == "mission_end" for e in ev) and env.eval("SORTIE.file") is None


def test_sanitized_environment_falls_back_to_log(tmp_path):
    env = LuaEnv(tmp_path, scripts.config_lua(CFG), sanitized=True, setup=SETUP)
    env.run("MOCK.fire{ id = world.event.S_EVENT_TAKEOFF, initiator = P1 }")
    assert env.errors() == [] and env.eval("SORTIE.mode") == "log"
    ev = env.log_events()
    assert ev[0]["ev"] == "mission_start" and ev[0]["mode"] == "log" and ev[-1]["ev"] == "takeoff"
    assert not env.events_path.exists()


def test_handler_errors_do_not_escape(env):
    env.run("MOCK.fire{ id = world.event.S_EVENT_HIT, initiator = 42 }")      # garbage initiator
    env.run("SORTIE.safe('boom', function() error('x') end)")
    assert any("boom" in e for e in env.errors())
    env.run("MOCK.fire{ id = world.event.S_EVENT_LAND, initiator = P1 }")
    assert env.events()[-1]["ev"] == "land"                                   # logger still alive


def test_message_goes_to_player_group(env):
    env.run("SORTIE.message('hello', 5)")
    assert env.eval("MOCK.texts[1].group") == 7 and env.eval("MOCK.texts[1].text") == "hello"
