"""Mod aircraft, plane guards on every NATO carrier, community scripts, JTACs and deck dressing."""
import zipfile

import dcs
import pytest

from sortie import addons, config, mods, theater, units
from sortie.ato import assign, planner
from sortie.campaign import ensure_plane_guards
from sortie.mission import builder, deck, loadouts, scripts
from tests.conftest import make_state

D = config.defaults()

# The CJS Super Hornet payload format: `local` station constants and ["name"] instead of
# ["unitType"], which pydcs's own parser cannot read; store ids are per-station wrappers.
SH_PAYLOADS = """
local WTL = 1
local OBL = 2
local CEN = 5
local unitPayloads = {
	["name"] = "FA-18E",
	["payloads"] = {
		[1] = {
			["name"] = "AIM-9X*2, GBU-12*2, FUEL*1",
			["pylons"] = {
				[WTL] = { ["CLSID"] = "{SUPERHORNET_PYLON_01_SW_1X_AIM-9X}", ["num"] = WTL },
				[OBL] = { ["CLSID"] = "{SUPERHORNET_PYLON_02_OB_MK_1X_GBU-12}", ["num"] = OBL },
				[CEN] = { ["CLSID"] = "{SUPERHORNET_PYLON_06_CN_FT_FPU-12_Fueltank}", ["num"] = CEN },
			},
			["tasks"] = { [1] = 32 },
		},
		[2] = {
			["name"] = "AIM-9X*2, GBU-38*2, FUEL*1",
			["pylons"] = {
				[WTL] = { ["CLSID"] = "{SUPERHORNET_PYLON_01_SW_1X_AIM-9X}", ["num"] = WTL },
				[OBL] = { ["CLSID"] = "{SUPERHORNET_PYLON_02_OB_MK_1X_GBU-38}", ["num"] = OBL },
				[CEN] = { ["CLSID"] = "{SUPERHORNET_PYLON_06_CN_FT_FPU-12_Fueltank}", ["num"] = CEN },
			},
			["tasks"] = { [1] = 32 },
		},
	},
}
return unitPayloads
"""
UH60_PAYLOADS = """
local unitPayloads = {
	["name"] = "UH-60L",
	["payloads"] = {
		[1] = { ["name"] = "Clean", ["pylons"] = {}, ["tasks"] = { [1] = 35 } },
	},
	["unitType"] = "UH-60L",
}
return unitPayloads
"""


@pytest.fixture
def mod_settings(tmp_path):
    sg = tmp_path / "sg" / "DCS.openbeta"
    sh = sg / "Mods" / "aircraft" / "CJS Super Hornet Mod v2.4" / "UnitPayloads"
    sh.mkdir(parents=True)
    (sh / "FA-18E.lua").write_text(SH_PAYLOADS, encoding="utf-8")
    uh = sg / "Mods" / "aircraft" / "uh60l" / "UnitPayloads"
    uh.mkdir(parents=True)
    (uh / "UH-60L.lua").write_text(UH60_PAYLOADS, encoding="utf-8")
    s = config.Settings(saved_games=str(sg), dcs_install=str(tmp_path / "none"), output_dir=str(tmp_path / "out"),
                        db_path=str(tmp_path / "s.db"), mods={"superhornet": True, "uh60l": True})
    loadouts.configure_from_settings(s)
    yield s
    mods.register(None)                      # leave pydcs as the other tests expect it
    loadouts.configure(None)


def test_mods_register_only_when_installed_and_on(mod_settings):
    assert units.aircraft_type("FA-18E") is not None and units.aircraft_type("UH-60L") is not None
    assert units.aircraft_type("A-4E-C") is None                # not installed
    assert units.year_of("FA-18E") == 1999 and "FA-18E" in units.flyable_modules()
    off = mod_settings.model_copy(update={"mods": {"superhornet": False, "uh60l": True}})
    mods.register(off)
    assert units.aircraft_type("FA-18E") is None and units.aircraft_type("UH-60L") is not None


def test_super_hornet_payloads_read_and_scored(mod_settings):
    p = loadouts._payloads("FA-18E")
    assert set(p) == {"AIM-9X*2, GBU-12*2, FUEL*1", "AIM-9X*2, GBU-38*2, FUEL*1"}
    assert loadouts.pick("FA-18E", "STRIKE") in p
    assert loadouts.describe("FA-18E", "AIM-9X*2, GBU-12*2, FUEL*1") == ["1 x AIM-9X", "1 x GBU-12", "1 x FPU-12 FUELTANK"]
    # weather swaps may only pick a store the mod's own payloads hang on that station
    t = units.aircraft_type("FA-18E")
    assert mods.station_clsids(t, 2) == ["{SUPERHORNET_PYLON_02_OB_MK_1X_GBU-12}", "{SUPERHORNET_PYLON_02_OB_MK_1X_GBU-38}"]
    from sortie import weather
    out, notes, keep, dead = weather.adapt(t, [(2, {"clsid": "{SUPERHORNET_PYLON_02_OB_MK_1X_GBU-12}"})],
                                           {"cloud_base_m": 600, "cloud_density": 9, "visibility_km": 3,
                                            "precip": "rain"})
    assert out[0][1]["clsid"] in mods.station_clsids(t, 2)


def test_uh60l_flies_plane_guard_in_navy_grey_and_mod_off_falls_back(mod_settings):
    assert mods.flown_type("SH-60B", "SAR") == ("UH-60L", "US Navy Grey", None)
    assert mods.flown_type("SH-60B", "TRANSPORT")[0] == "SH-60B"
    mods.register(mod_settings.model_copy(update={"mods": {}}))
    ac, _, note = mods.flown_type("FA-18E", "CAP")
    assert ac == "FA-18C_hornet" and "off" in note
    assert mods.flown_type("SH-60B", "SAR")[0] == "SH-60B"


def test_mod_squadrons_join_the_theater_while_on(mod_settings):
    t = theater.load("gulf_crisis")
    ids = {s.id for s in t.squadrons}
    assert {"vfa143", "vfa102", "vaq141"} <= ids and "160soar" not in ids      # AH-6J mod not installed
    assert not theater.validate(t)


def test_mission_with_mods(mod_settings, tmp_path):
    ths = {t.id: t for t in theater.list_theaters()}
    st = make_state(ths, "gulf_crisis", squadron="vfa143", settings=mod_settings)
    st.meta.owned_modules = units.flyable_modules()
    ato = planner.generate_ato(st, D)
    r = assign.assign_player(st, ato, D, 1)
    res = builder.build_mission(st, ato, r["reason"], mod_settings, out_dir=tmp_path / "o", with_moose=False)
    guards = [v for v in res.manifest.values() if v.get("role") == "plane_guard"]
    assert {g["base"] for g in guards} == {"cvn73", "lha1"} and all(g["aircraft"] == "UH-60L" for g in guards)
    m = dcs.Mission()
    m.load_file(res.path)
    heli = [g for c in m.coalition["blue"].countries.values() for g in c.helicopter_group if g.units[0].type == "UH-60L"]
    assert heli and all(g.units[0].livery_id == "US Navy Grey" for g in heli)
    me = [g for c in m.coalition["blue"].countries.values() for g in c.plane_group if g.units[0].type == "FA-18E"]
    assert me


# ---- plane guards ---------------------------------------------------------------------------------
def test_every_nato_carrier_gets_a_plane_guard(gulf):
    gulf.squadrons = {k: v for k, v in gulf.squadrons.items() if not ("SAR" in v.tasks)}
    added = ensure_plane_guards(gulf)
    assert sorted(added) == ["cvn73_pg", "lha1_pg"]
    assert gulf.squadrons["lha1_pg"].aircraft == "SH-60B" and gulf.squadrons["lha1_pg"].airbase_id == "lha1"
    assert ensure_plane_guards(gulf) == []                       # idempotent


def test_no_helicopter_plane_guard_in_1944(forager):
    assert ensure_plane_guards(forager) == []


def test_both_carriers_keep_plane_guard_under_tight_limits(theaters, tmp_path):
    from tests.test_coop_timeline import _build
    st, ato, res, _ = _build(theaters, tmp_path, squadron="77fs", profile="light")
    bases = {v.get("base") for v in res.manifest.values() if v.get("role") == "plane_guard"}
    assert bases == {"cvn73", "lha1"}


# ---- community scripts ----------------------------------------------------------------------------
SPLASH = '''-- header
splash_damage_options = {
    ---------------------------------------------------------------------- Debug and Messages ------------
    ["game_messages"] = false, --enable some messages on screen
    ---------------------------------------------------------------------- Basic Splash Settings ---------
    ["overall_scaling"] = 1,    --overall scaling for explosive power
    ["napalm_override_weapons"] = "Mk_82,SAMP125LD", --list
    ["allunits_advanced_effect_order"] = {"2", "7"},  --a table: left as it is
}
----[[ end ]]----
if splash_damage_options.game_messages then end
'''


def test_splash_schema_and_patch(tmp_path, monkeypatch):
    v = tmp_path / "vendor"
    v.mkdir()
    (v / "Splash_Damage.lua").write_text(SPLASH, encoding="utf-8")
    monkeypatch.setattr(addons, "VENDOR", v)
    sch = addons.splash_schema()
    assert [f["key"] for f in sch] == ["game_messages", "overall_scaling", "napalm_override_weapons"]
    assert sch[1]["section"] == "Basic Splash Settings" and sch[1]["type"] == "number"
    s = config.Settings(addons={"splash": {"enabled": True, "params": {"overall_scaling": "1.5", "nope": 3,
                                                                        "game_messages": False}}})
    assert addons.changed_params(s, "splash") == {"overall_scaling": 1.5}
    out = addons.patched_splash(s, tmp_path).read_text(encoding="utf-8")
    i = out.index('splash_damage_options["overall_scaling"] = 1.5')
    assert out.index('{"2", "7"}') < i < out.index("----[[ end") < out.index("if splash_damage_options")


def test_growler_is_shelved(tmp_path, monkeypatch):
    v = tmp_path / "vendor"
    v.mkdir()
    (v / "Growler_AEA.lua").write_text("-- stub\n", encoding="utf-8")
    monkeypatch.setattr(addons, "VENDOR", v)
    s = config.Settings(addons={"growler": {"enabled": True}})
    assert not addons.is_on(s, "growler") and addons.growler_types(s) == []
    assert "growler" not in [a["key"] for a in addons.status(s)]
    assert addons.files_for_mission(s, tmp_path)["delayed"] == []


def test_addon_files_and_order(tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "SHELVED", set())                 # the Growler wiring, for when it returns
    v = tmp_path / "vendor"
    v.mkdir()
    for n in ("Splash_Damage.lua", "mist.lua", "skynet-iads-compiled.lua", "HoundElint.lua", "Growler_AEA.lua"):
        (v / n).write_text(SPLASH if n.startswith("Splash") else "-- stub\n", encoding="utf-8")
    monkeypatch.setattr(addons, "VENDOR", v)
    s = config.Settings(addons={k: {"enabled": True} for k in addons.INFO})
    files = addons.files_for_mission(s, tmp_path)
    assert [p.name for p in files["before"]] == ["mist.lua"]
    assert [p.name for p in files["after"]] == ["Splash_Damage.lua", "skynet-iads-compiled.lua", "HoundElint.lua"]
    assert [p.name for p in files["delayed"]] == ["Growler_AEA.lua"]
    m = dcs.Mission()
    cfg = {"addons": {"skynet": {}}, "atc": {}}
    names = scripts.attach(m, cfg, False, False, {**files, "delay_s": 7})
    assert names.index("mist.lua") < names.index("sortie_config.lua") < names.index("sortie_core.lua")
    assert names.index("sortie_spawn.lua") < names.index("Splash_Damage.lua") < names.index("sortie_addons.lua")
    assert names[-1] == "Growler_AEA.lua"
    assert any(t.comment == "SORTIE late scripts" for t in m.triggerrules.triggers)


def test_skynet_and_hound_config_from_campaign(theaters, tmp_path, monkeypatch):
    from tests.test_coop_timeline import _build
    v = tmp_path / "vendor"
    v.mkdir()
    for n in ("mist.lua", "skynet-iads-compiled.lua", "HoundElint.lua"):
        (v / n).write_text("-- stub\n", encoding="utf-8")
    monkeypatch.setattr(addons, "VENDOR", v)
    ad = {"skynet": {"enabled": True, "params": {"go_live_pct": 80}}, "hound": {"enabled": True}}
    st, ato, res, _ = _build(theaters, tmp_path, squadron="77fs", addons=ad)
    assert "skynet-iads-compiled.lua" in res.scripts and "sortie_addons.lua" in res.scripts
    with zipfile.ZipFile(res.path) as z:
        cfg = z.read(next(n for n in z.namelist() if n.endswith("sortie_config.lua"))).decode()
    assert '["go_live_pct"] = 80' in cfg and '["name"] = "RED"' in cfg and "S|sam|sa10_ba|1" in cfg
    assert '["prebriefed"]' in cfg
    # search radar first in every SAM group (Skynet reads the site's radar from its first unit)
    m = dcs.Mission()
    m.load_file(res.path)
    g = m.find_group("S|sam|sa10_ba|1")
    assert g is not None and g.units[0].type == "S-300PS 64H6E sr"


# ---- JTAC and deck -----------------------------------------------------------------------------
def test_jtac_with_cas_package(theaters, tmp_path):
    from tests.test_coop_timeline import _build
    st, ato, res, _ = _build(theaters, tmp_path, squadron="74fs")
    if not any(p.mission in ("CAS", "INTERDICTION") for p in ato.packages if p.coalition == "blue"):
        pytest.skip("no CAS this cycle")
    jt = res.briefing.get("jtacs") or []
    assert jt and jt[0]["code"] == "1688" and jt[0]["freq"] == 133.0
    m = dcs.Mission()
    m.load_file(res.path)
    g = m.find_group(jt[0]["group"])
    assert g is not None and any(getattr(t, "Id", "") == "FAC" for t in g.points[0].tasks)
    assert "JTAC: " in m.description_text()


def test_deck_plan_keeps_reserve_and_mixes_types(theaters, tmp_path):
    from tests.test_coop_timeline import _build
    st, ato, res, _ = _build(theaters, tmp_path, squadron="vfa27")
    with zipfile.ZipFile(res.path) as z:
        cfg = z.read(next(n for n in z.namelist() if n.endswith("sortie_config.lua"))).decode()
    assert '["deck"]' in cfg and '["kind"] = "cvn"' in cfg and '["kind"] = "lha"' in cfg
    flying = sum(f.count for fid in res.selection["flights"] for f in [ato.find_flight(fid)[1]]
                 if st.squadrons[f.squadron_id].airbase_id == "cvn73")
    assert f'["reserve"] = {flying + deck.MARGIN}' in cfg


def test_deck_and_jtac_switch_off(theaters, tmp_path):
    from tests.test_coop_timeline import _build
    st, ato, res, _ = _build(theaters, tmp_path, squadron="74fs", deck_statics=False, jtac=False)
    with zipfile.ZipFile(res.path) as z:
        cfg = z.read(next(n for n in z.namelist() if n.endswith("sortie_config.lua"))).decode()
    assert '["deck"] = {}' in cfg and '["jtacs"] = {}' in cfg
