import zipfile

import pytest

from sortie import config
from sortie.ato import assign, planner
from sortie.atc import luacfg, procedures as P
from sortie.mission import builder, loadouts, scripts
from tests.conftest import make_state
from tests.luaenv import CORE, LuaEnv

D = config.defaults()


# ---- Python phrase generation ---------------------------------------------------------------
def test_procedure_selection():
    assert P.procedure_set("nato", "modern") == "nato" and P.procedure_set("soviet", "coldwar") == "soviet"
    assert P.procedure_set("nato", "ww2") == "ww2" and P.procedure_set("ww2", "ww2") == "ww2"


def test_features_by_era():
    ww2 = P.features("ww2", ["CARRIER", "GCI"])
    assert ww2["gci"] and ww2["tower"] and ww2["picture"]
    assert not (ww2["awacs"] or ww2["tanker"] or ww2["declare"] or ww2["bullseye"] or ww2["csar"] or ww2["airboss"])
    modern = P.features("nato", ["AWACS", "TANKER", "GCI", "CARRIER"])
    assert modern["awacs"] and modern["tanker"] and modern["declare"] and modern["bullseye"] and modern["airboss"]
    assert not P.features("soviet", [])["gci"]


def test_formatting_per_procedure():
    assert P.fmt_range(37040, "nato") == "20 miles" and P.fmt_range(37040, "soviet") == "37 kilometres"
    assert P.fmt_altitude(7620, "nato") == "25 thousand" and P.fmt_altitude(7620, "soviet") == "7600 metres"
    assert P.fmt_altitude(3048, "ww2") == "10" and P.fmt_bearing(7.4) == "007" and P.fmt_bearing(360) == "000"
    assert P.aspect(180, 0) == "hot" and P.aspect(0, 0) == "cold" and P.aspect(90, 0) == "beaming"
    assert P.aspect(225, 0) == "flanking"


def test_calls_nato_soviet_ww2():
    nato = P.contact_call("nato", "bogey_dope", "Viper 1", "Darkstar", 45, 55560, 9144, 225)
    assert nato == "Viper 1, Darkstar, group BRAA 045/30 miles, 30 thousand, hot, hostile."
    sov = P.contact_call("soviet", "threat", "201", "Kupol", 270, 30000, 5000, 90)
    assert sov == "201, Kupol. Attention! Enemy azimuth 270, range 30 kilometres, height 5000 metres!"
    ww2 = P.contact_call("ww2", "bogey_dope", "Rebel 1", "Base", 90, 37040, 3048)
    assert ww2 == "Rebel 1, Base. Vector 090, bogeys 20 miles, angels 10. Buster."
    assert "BRAA" not in ww2 and "bullseye" not in ww2
    assert P.render("ww2", "vector_tanker", callsign="x") == ""          # no tanker calls in 1944
    assert P.render("ww2", "csar", callsign="x") == ""


def test_picture_calls():
    assert P.picture_call("nato", "Viper 1", "Darkstar", []) == "Viper 1, Darkstar, picture clean."
    groups = [{"bearing": 90, "range_m": 74080, "alt_m": 6096, "heading": 270},
              {"bearing": 120, "range_m": 92600, "alt_m": 3048, "heading": 0}]
    txt = P.picture_call("nato", "Viper 1", "Darkstar", groups)
    assert txt.startswith("Viper 1, Darkstar, picture: 2 groups. Group bullseye 090/40 miles, 20 thousand, hot")
    assert P.picture_call("soviet", "201", "Kupol", groups[:1]).startswith("201, Kupol. 1 target. Target azimuth 090")
    assert "plot" in P.picture_call("ww2", "Rebel", "Base", groups[:1])


def test_all_procedures_define_core_phrases():
    core = {"checkin", "picture_clean", "picture", "group", "bogey_dope", "threat", "merged", "vector_home",
            "startup", "taxi", "takeoff", "landing", "landed", "splash"}
    for proc in P.PROCEDURES:
        assert core <= set(P.PHRASES[proc]), proc


# ---- config -----------------------------------------------------------------------------------
def _cfg(theaters, tid, **settings_kw):
    s = config.Settings(atc_enabled=True, **settings_kw)
    st = make_state(theaters, tid)
    ato = planner.generate_ato(st, D)
    assign.assign_player(st, ato, D)
    return st, ato, luacfg.build(st, ato, s, {})


def test_luacfg_default_off_and_per_theater(theaters):
    st = make_state(theaters, "gulf_crisis")
    ato = planner.generate_ato(st, D)
    assign.assign_player(st, ato, D)
    assert luacfg.build(st, ato, config.Settings(), {}) == {"enabled": False}
    assert config.Settings().atc_enabled is False and config.Settings().voice == "off"
    _, _, gulf = _cfg(theaters, "gulf_crisis", voice="windows")
    assert gulf["procedure"] == "nato" and gulf["voice"] == "windows" and gulf["features"]["awacs"]
    assert gulf["controller"]["callsign"] and gulf["tankers"] and gulf["units"] == "imperial"
    _, _, ww2 = _cfg(theaters, "forager_1944")
    assert ww2["procedure"] == "ww2" and not ww2["features"]["awacs"] and ww2["tankers"] == []
    assert ww2["controller"]["callsign"] == "Base" and "vector_tanker" not in ww2["phrases"]
    s = config.Settings(atc_enabled=True)
    st = make_state(theaters, "coldwar_1985", side="red", squadron="33iap")
    ato = planner.generate_ato(st, D)
    assign.assign_player(st, ato, D)
    red = luacfg.build(st, ato, s, {})
    assert red["procedure"] == "soviet" and red["units"] == "metric" and red["controller"]["callsign"] == "Kupol"
    assert not red["features"]["awacs"] and red["features"]["gci"]


def test_mission_embeds_atc_script_only_when_enabled(theaters, tmp_path):
    loadouts.configure(None)
    for enabled in (False, True):
        s = config.Settings(saved_games=str(tmp_path / "sg"), dcs_install=str(tmp_path / "n"),
                            output_dir=str(tmp_path / str(enabled)), atc_enabled=enabled)
        st = make_state(theaters, "gulf_crisis", settings=s)
        ato = planner.generate_ato(st, D)
        r = assign.assign_player(st, ato, D)
        res = builder.build_mission(st, ato, r["reason"], s, with_moose=False)
        with zipfile.ZipFile(res.path) as z:
            assert ("l10n/DEFAULT/sortie_atc.lua" in z.namelist()) is enabled
        assert ("sortie_atc.lua" in res.scripts) is enabled


# ---- the Lua side, same phrases ------------------------------------------------------------------
BASE = {"version": 1, "campaign": "t", "turn": 1, "sortie": "s1", "player_side": 2,
        "player_group": "S|flt|B1-01-1|1", "runtime_subdir": "Missions\\SORTIE\\runtime\\",
        "events_file": "events.jsonl", "manifest": {}, "late_groups": [], "warehouses": {}}
SETUP = """
MOCK.airbase('Al Dhafra AFB')
P1 = MOCK.unit{ name = 'S|flt|B1-01-1|1 Pilot #1', type = 'F-16C_50', coalition = 2, player = 'Rook',
                x = 0, z = 0, alt = 6000, air = true, vx = 200, vz = 0 }
MOCK.group{ name = 'S|flt|B1-01-1|1', side = 2, units = { P1 }, id = 7 }
E1 = MOCK.unit{ name = 'bandit-1', type = 'MiG-29A', coalition = 1, x = 55560, z = 0, alt = 9144, air = true,
                vx = -250, vz = 0 }
MOCK.group{ name = 'bandits', side = 1, units = { E1 } }
"""


def _atc_env(tmp_path, proc, voice="off", extra_setup="", caps=("AWACS", "TANKER", "GCI")):
    atc = {"enabled": True, "procedure": proc, "voice": voice, "features": P.features(proc, list(caps)),
           "phrases": P.PHRASES[proc], "coalition": 2, "bullseye": {"lat": 0.0, "lon": 0.0},
           "home": {"name": "Al Dhafra AFB", "kind": "airfield", "freq": 251.0},
           "controller": {"callsign": "Darkstar" if proc == "nato" else P.gci_callsign(proc), "freq": 251.5},
           "tankers": [], "picture_interval": 120, "threat_range_m": P.THREAT_RANGE_M[proc],
           "picture_range_m": 185000, "player_callsign": "Viper 1",
           "srs": {"path": "C:\\SRS", "port": 5002, "culture": "en-US", "google_credentials": ""}}
    return LuaEnv(tmp_path, scripts.config_lua({**BASE, "atc": atc}), setup=SETUP + extra_setup,
                  scripts=CORE + ["sortie_atc.lua"])


@pytest.mark.parametrize("proc", ["nato", "soviet", "ww2"])
def test_lua_bogey_dope_matches_python(tmp_path, proc):
    env = _atc_env(tmp_path, proc)
    said = env.eval("SORTIE.atc.bogey_dope()")
    ctrl = "Darkstar" if proc == "nato" else P.gci_callsign(proc)
    assert said == P.contact_call(proc, "bogey_dope", "Viper 1", ctrl, 0, 55560, 9144, 180)
    assert env.errors() == []
    assert env.eval("MOCK.texts[#MOCK.texts].group") == 7               # shown on screen with voice off
    assert [e for e in env.events() if e["ev"] == "atc"][-1]["text"] == said


def test_lua_formatting_matches_python(tmp_path):
    for proc in ("nato", "soviet", "ww2"):
        env = _atc_env(tmp_path / proc, proc)
        for m in (900, 3048, 7620, 12000):
            assert env.eval(f"SORTIE.atc.fmt_altitude({m})") == P.fmt_altitude(m, proc)
        for m in (5000, 37040, 151234):
            assert env.eval(f"SORTIE.atc.fmt_range({m})") == P.fmt_range(m, proc)
        for hdg, brg in ((180, 0), (0, 0), (90, 0), (225, 0), (10, 200)):
            assert env.eval(f"SORTIE.atc.aspect({hdg}, {brg})") == P.aspect(hdg, brg)
        assert env.eval("SORTIE.atc.fmt_bearing(7.4)") == "007"


def test_lua_picture_threat_and_menu(tmp_path):
    env = _atc_env(tmp_path, "nato")
    assert env.eval("SORTIE.atc.picture()").startswith("Viper 1, Darkstar, picture: 1 group. Group bullseye 000/30 miles")
    env.run("E1.x = 30000; MOCK.advance(16)")                          # inside 25 nm
    assert any("threat BRAA 000/16 miles" in t for t in env.eval("SORTIE.atc.said").values())
    n = len(list(env.eval("SORTIE.atc.said").values()))
    env.run("MOCK.advance(16)")                                         # not repeated within 60 s
    assert len([t for t in env.eval("SORTIE.atc.said").values() if "threat" in t]) == 1
    env.run("E1.x = 2000; MOCK.advance(60)")
    assert any(t.endswith("merged.") for t in env.eval("SORTIE.atc.said").values())
    menu = set(env.eval("MOCK.menu").keys())
    assert {"Request picture", "Bogey dope", "Declare (contact on the nose)", "Vector to home base",
            "Vector to tanker"} <= menu
    env.run("MOCK.groups['bandits'].exists = false; MOCK.groups['bandits'].active = false")
    assert env.eval("SORTIE.atc.picture()") == "Viper 1, Darkstar, picture clean."
    assert env.errors() == []


def test_lua_ww2_has_only_simple_gci(tmp_path):
    env = _atc_env(tmp_path, "ww2", caps=("GCI",))
    menu = set(env.eval("MOCK.menu").keys())
    assert "Declare (contact on the nose)" not in menu and "Vector to tanker" not in menu
    said = env.eval("SORTIE.atc.picture()")
    assert "plot" in said and "bullseye" not in said.lower() and "BRAA" not in said
    assert env.eval("SORTIE.atc.declare()") is None
    env.run("MOCK.fire{ id = world.event.S_EVENT_EJECTION, initiator = P1 }")
    assert not [e for e in env.events() if e["ev"] == "csar"]


def test_lua_tower_sequence_and_splash(tmp_path):
    env = _atc_env(tmp_path, "nato")
    env.run("""
      P1.air = false
      MOCK.fire{ id = world.event.S_EVENT_ENGINE_STARTUP, initiator = P1 }
      MOCK.fire{ id = world.event.S_EVENT_TAKEOFF, initiator = P1 }
      P1.air = true
      MOCK.fire{ id = world.event.S_EVENT_KILL, initiator = P1, target = E1 }
      P1.x = 100000; MOCK.advance(21)
      P1.x = 30000; MOCK.advance(20)
      P1.x = 8000; MOCK.advance(20)
      MOCK.fire{ id = world.event.S_EVENT_LAND, initiator = P1 }
      MOCK.fire{ id = world.event.S_EVENT_EJECTION, initiator = P1 }
    """)
    said = list(env.eval("SORTIE.atc.said").values())
    keys = [e["key"] for e in env.events() if e["ev"] == "atc"]
    for k in ("startup", "taxi", "departure", "checkin", "splash", "inbound", "landing", "landed", "csar"):
        assert k in keys, k
    assert keys.index("startup") < keys.index("departure") < keys.index("inbound") < keys.index("landing")
    assert any("start-up approved" in t for t in said) and any("cleared to land" in t for t in said)
    assert [e for e in env.events() if e["ev"] == "csar"] and env.errors() == []


def test_lua_voice_uses_msrs_when_available_else_text(tmp_path):
    fake = """
    MOCK.spoken = {}
    MSRS = { Provider = { WINDOWS = 'win', GOOGLE = 'gcloud' } }
    function MSRS:New(path, freq, mod) local o = { path = path, freq = freq }; setmetatable(o, { __index = MSRS }); MOCK.msrs = o; return o end
    function MSRS:SetPort(p) self.port = p end
    function MSRS:SetCoalition(c) self.coalition = c end
    function MSRS:SetCulture(c) self.culture = c end
    function MSRS:SetProvider(p) self.provider = p end
    function MSRS:SetGoogle(p) self.google = p end
    function MSRS:PlayText(text, delay) MOCK.spoken[#MOCK.spoken + 1] = text end
    """
    env = _atc_env(tmp_path / "a", "nato", voice="google", extra_setup=fake)
    said = env.eval("SORTIE.atc.bogey_dope()")
    assert env.eval("MOCK.msrs.provider") == "gcloud" and env.eval("MOCK.msrs.path") == "C:\\SRS"
    assert env.eval("MOCK.spoken[#MOCK.spoken]") == said                 # spoken ...
    assert env.eval("MOCK.texts[#MOCK.texts].text") == said              # ... and still shown as text
    env = _atc_env(tmp_path / "b", "nato", voice="piper", extra_setup=fake)
    assert env.eval("MOCK.msrs.provider") == "win"                       # documented fallback
    env = _atc_env(tmp_path / "c", "nato", voice="windows")              # MOOSE not loaded
    assert env.eval("SORTIE.atc.msrs") is None and env.eval("SORTIE.atc.bogey_dope()") and env.errors() == []
    env = _atc_env(tmp_path / "d", "nato", voice="off", extra_setup=fake)
    env.eval("SORTIE.atc.bogey_dope()")
    assert env.eval("#MOCK.spoken") == 0
