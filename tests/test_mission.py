import zipfile

import dcs
import pytest

from sortie import config
from sortie.ato import assign, planner
from sortie.mission import briefing, budget, builder, forces, loadouts, scripts, warehouses
from tests.conftest import make_state

D = config.defaults()
IDS = ["coldwar_1985", "forager_1944", "gulf_crisis"]


def _build(theaters, tid, tmp_path, coop=1, profile="auto", atc=False, **kw):
    s = config.Settings(saved_games=str(tmp_path / "sg"), dcs_install=str(tmp_path / "none"),
                        output_dir=str(tmp_path / "out"), coop_slots=coop, profile=profile, atc_enabled=atc)
    loadouts.configure(None)
    st = make_state(theaters, tid, settings=s, **kw)
    ato = planner.generate_ato(st, D)
    res = assign.assign_player(st, ato, D, coop)
    return st, ato, builder.build_mission(st, ato, res["reason"], s, with_moose=False), s


def _groups(m, side):
    out = []
    for c in m.coalition[side].countries.values():
        out += c.plane_group + c.helicopter_group
    return out


@pytest.mark.parametrize("tid", IDS)
def test_build_each_theater(theaters, tid, tmp_path):
    st, ato, res, _ = _build(theaters, tid, tmp_path)
    assert res.ok and res.filename == f"SORTIE_{tid}_T001.miz"
    with zipfile.ZipFile(res.path) as z:
        names = z.namelist()
        mission = z.read("mission").decode()
        cfg = z.read("l10n/DEFAULT/sortie_config.lua").decode()
    for n in ["sortie_config.lua"] + scripts.CORE_SCRIPTS:
        assert f"l10n/DEFAULT/{n}" in names
    assert mission.count("a_do_script_file") == 2 * len(res.scripts) and '"triggerStart"' in mission
    assert res.scripts[0] == "sortie_config.lua" and res.scripts[1] == "sortie_json.lua"
    assert f'["sortie"] = "{res.sortie_id}"' in cfg and "S|flt|" in cfg
    m = dcs.Mission()
    m.load_file(res.path)
    from datetime import timedelta
    start = st.now + timedelta(seconds=res.stats["t0_s"])
    assert m.start_time.strftime("%Y-%m-%dT%H:%M") == start.strftime("%Y-%m-%dT%H:%M")
    assert res.stats["peak_airborne"] <= config.profile_limits(res.stats["profile"])["max_air"]
    assert res.stats["aircraft"] >= res.stats["peak_airborne"]
    assert set(st.meta.countries["blue"]) == set(m.coalition["blue"].countries)
    if tid == "forager_1944":
        assert any("MarianaIslandsWWII" in w for w in res.warnings)


def test_single_player_slot(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, "gulf_crisis", tmp_path)
    m = dcs.Mission()
    m.load_file(res.path)
    g = m.find_group(budget.gname("flt", ato.player_flight_id))
    skills = [u.skill.value for u in g.units]
    assert skills[0] == "Player" and "Client" not in skills and all(s != "Player" for s in skills[1:])
    assert g.points[0].type == "TakeOffParking" and g.points[-1].type == "Land"
    assert g.frequency == ato.find_flight(ato.player_flight_id)[1].freq
    others = [u.skill.value for side in ("blue", "red") for x in _groups(m, side) if x.id != g.id for u in x.units]
    assert others and not {"Player", "Client"} & set(others)


def test_coop_client_slots(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, "gulf_crisis", tmp_path, coop=3)
    m = dcs.Mission()
    m.load_file(res.path)
    g = m.find_group(budget.gname("flt", ato.player_flight_id))
    skills = [u.skill.value for u in g.units]
    assert skills[:3] == ["Client"] * 3 and "Player" not in skills and len(skills) >= 3
    assert res.stats["coop_slots"] == 3


def test_carrier_player_flight(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, "forager_1944", tmp_path)
    m = dcs.Mission()
    m.load_file(res.path)
    g = m.find_group(budget.gname("flt", ato.player_flight_id))
    assert g.units[0].unit_type.id == "F4U-1D" and g.units[0].skill.value == "Player"
    ship = m.find_group(budget.gname("nav", "cv_essex"))
    assert ship is not None and g.points[0].link_unit == ship.units[0].id
    assert res.manifest[budget.gname("nav", "cv_essex")]["carrier_unit"]
    # the carrier has its own (limited fuel) warehouse entry
    assert m.warehouses.warehouses[ship.units[0].id]["unlimitedFuel"] is False


def test_profiles_scale_the_mission(theaters, tmp_path):
    light = _build(theaters, "gulf_crisis", tmp_path / "l", profile="light")[2]
    heavy = _build(theaters, "gulf_crisis", tmp_path / "h", profile="heavy")[2]
    assert light.stats["peak_airborne"] <= 24 and heavy.stats["peak_airborne"] <= 72
    assert light.stats["aircraft"] < heavy.stats["aircraft"]
    assert light.stats["ground_groups"] <= heavy.stats["ground_groups"]
    assert light.selection["bubble_km"] < heavy.selection["bubble_km"]


def test_selection_always_keeps_player_package_and_target(gulf):
    ato = planner.generate_ato(gulf, D)
    assign.assign_player(gulf, ato, D)
    tiny = {"max_air": 1, "max_ground_groups": 1, "max_naval_groups": 0, "bubble_km": 5, "spawn_km": 3,
            "despawn_km": 6}
    sel = budget.select(gulf, ato, tiny)
    pkg, flt = ato.find_flight(ato.player_flight_id)
    assert sel.flights[0] == flt.id and {f.id for f in pkg.flights} <= set(sel.flights)
    assert pkg.target.id in sel.sam_sites + sel.supply_nodes + sel.routes + sel.naval_groups + \
        [g for g in sel.ground_units] or pkg.target.kind in ("front", "airbase")
    ato.player_flight_id = None
    with pytest.raises(ValueError):
        budget.select(gulf, ato, tiny)


def test_name_contract():
    n = budget.gname("sam", "sa10_ba", 2)
    assert n == "S|sam|sa10_ba|2" and budget.parse_name(n) == ("sam", "sa10_ba", 2)
    assert budget.parse_name("S|flt|B1-03-1|1 Pilot #2") == ("flt", "B1-03-1", 1)
    assert budget.parse_name("S|gnd|us1bct|1 #7") == ("gnd", "us1bct", 1)
    assert budget.parse_name("Random Group") is None and budget.parse_name("") is None


def test_warehouses_written_from_state(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, "gulf_crisis", tmp_path)
    m = dcs.Mission()
    m.load_file(res.path)
    ap = m.terrain.airports["Al Dhafra AFB"]
    assert ap.coalition == "BLUE" and ap.unlimited_fuel is False and ap.unlimited_munitions is False
    assert ap.unlimited_aircrafts is True and ap.jet_init == 1500.0
    assert m.terrain.airports["Bandar Abbas Intl"].coalition == "RED"
    assert m.terrain.airports["Dubai Intl"].coalition == "NEUTRAL"       # not in the campaign


def test_warehouse_lua_table_and_readback(gulf):
    b = gulf.airbases["dhafra"]
    b.munitions = {"weapons.missiles.AIM_120C": 30}
    b.munition_level = 0.5
    t = warehouses.lua_table(gulf, D["logistics"], {"cvn73": "S|nav|cvn73|1 #1"})
    assert t["Al Dhafra AFB"]["weapons"] == {"weapons.missiles.AIM_120C": 30}
    assert t["Al Dhafra AFB"]["default_stock"] == 40 and t["Al Dhafra AFB"]["aircraft"]["F-16C_50"] == 18
    assert t["S|nav|cvn73|1 #1"]["id"] == "cvn73"
    notes = warehouses.apply_readback(gulf, {"dhafra": {
        "liquids_start": {"0": 2000.0, "1": 10.0}, "liquids_end": {"0": 1500.0, "1": 10.0},
        "weapons": {"weapons.missiles.AIM_120C": 20, "weapons.bombs.Mk_82": 80}}, "nope": {}}, D["logistics"])
    assert b.fuel.jet == 1125.0 and b.munitions["weapons.missiles.AIM_120C"] == 20
    assert b.munition_level == round((20 + 80) / 160, 3) and notes


def test_damaged_entities_spawn_degraded(theaters, tmp_path):
    s = config.Settings(saved_games=str(tmp_path / "sg"), dcs_install=str(tmp_path / "n"), output_dir=str(tmp_path))
    st = make_state(theaters, "gulf_crisis", settings=s)
    for n in st.supply_nodes.values():
        n.health = 0.5
    assert forces.scaled_units({"T-72B": 10, "BMP-2": 10}, 1.0) == {"T-72B": 6, "BMP-2": 6}
    assert forces.scaled_units({"T-72B": 10}, 0.01) == {"T-72B": 1}
    ato = planner.generate_ato(st, D)
    r = assign.assign_player(st, ato, D)
    res = builder.build_mission(st, ato, r["reason"], s, with_moose=False)
    nodes = [v for v in res.manifest.values() if v["kind"] == "supply_node"]
    assert nodes and sum(1 for v in nodes if v["dead"]) == len(nodes) // 2


def test_briefing_contents(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, "gulf_crisis", tmp_path)
    b = res.briefing
    assert b["assigned"] and b["reason"] and b["objective"] and b["tot"] and b["waypoints"]
    assert b["flight"]["callsign"] and b["package"]["flights"] and b["awacs"] and b["tankers"]
    txt = briefing.text(st, b)
    for word in ("TASKING", "WHY YOU", "ROUTE", "RADIO", "AWACS", "TANKER", "TOT"):
        assert word in txt
    assert briefing.build(st, ato.model_copy(update={"player_flight_id": None}), "stand down")["assigned"] is False


def test_build_errors_are_reported_not_hidden(theaters, tmp_path, gulf):
    s = config.Settings(output_dir=str(tmp_path), dcs_install=str(tmp_path), saved_games=str(tmp_path))
    ato = planner.generate_ato(gulf, D)
    with pytest.raises(builder.BuildError):
        builder.build_mission(gulf, ato, "no flight", s)              # player not assigned
    assign.assign_player(gulf, ato, D)
    gulf.meta.terrain = "Atlantis"
    with pytest.raises(builder.BuildError):
        builder.build_mission(gulf, ato, "x", s)
    assert not list(tmp_path.glob("*.miz"))


def test_verify_miz_detects_problems(tmp_path):
    bad = tmp_path / "bad.miz"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("mission", "mission = {}")
    probs = builder.verify_miz(bad, ["sortie_json.lua"])
    assert any("warehouses" in p for p in probs) and any("sortie_json.lua" in p for p in probs)


def test_main_task_mapping():
    from sortie.mission.flights import main_task
    assert main_task("F-16C_50", "SEAD").name == "SEAD"
    assert main_task("F-15C", "ESCORT").name == "Escort"
    assert main_task("E-3A", "AWACS").name == "AWACS"
    assert main_task("F-15C", "STRIKE").name == "CAP"          # falls back to the airframe default
