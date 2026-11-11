import copy

from sortie import config, models as M
from sortie.models_ato import Ato, Flight, Package, Target
from sortie.sim import airwar, ground, production, readiness, supply, turn

D = config.defaults()


def _pkg(pid, side, mission, target, flights):
    return Package(id=pid, coalition=side, mission=mission, target=target, flights=flights)


def _flt(fid, st, sq_id, task, n=4):
    sq = st.squadrons[sq_id]
    return Flight(id=fid, squadron_id=sq_id, coalition=sq.coalition, aircraft=sq.aircraft, count=n, task=task)


def test_supply_flows_and_delivers(gulf):
    st = gulf
    st.airbases["dhafra"].fuel.jet = 100
    st.airbases["dhafra"].munition_level = 0.5
    st.airbases["dhafra"].munitions = {"weapons.missiles.AIM_120C": 40}
    rep = supply.run_supply(st, D)
    assert rep["produced"]["fac_mussafah"] == 600
    assert rep["moved"]["fac_mussafah__port_jebelali"] > 0
    assert st.airbases["dhafra"].fuel.jet > 100
    assert st.airbases["dhafra"].munition_level > 0.5
    assert st.airbases["dhafra"].munitions["weapons.missiles.AIM_120C"] > 40      # items scale with level
    assert st.airbases["cvn73"].fuel.jet == 1500                                  # full carrier stays full


def test_destroyed_node_cuts_resupply(gulf):
    a, b = copy.deepcopy(gulf), copy.deepcopy(gulf)
    for st in (a, b):
        st.airbases["lar"].fuel.jet = 0
        st.supply_nodes["dep_lar"].stock = 0
    b.supply_nodes["fac_shiraz"].health = 0.0
    supply.run_supply(a, D)
    supply.run_supply(a, D)
    supply.run_supply(b, D)
    rep = supply.run_supply(b, D)
    assert a.airbases["lar"].fuel.jet > 0
    assert b.airbases["lar"].fuel.jet == 0
    assert "fac_shiraz" not in rep["produced"]


def test_interdiction_reduces_flow_and_decays(gulf):
    a, b = copy.deepcopy(gulf), copy.deepcopy(gulf)
    b.supply_routes["fac_shiraz__dep_lar"].interdiction = 0.8
    ra, rb = supply.run_supply(a, D), supply.run_supply(b, D)
    assert rb["moved"]["fac_shiraz__dep_lar"] < ra["moved"]["fac_shiraz__dep_lar"]
    assert b.supply_routes["fac_shiraz__dep_lar"].interdiction == 0.4


def test_ground_units_starve_without_supply(gulf):
    gulf.supply_nodes["port_bandarabbas"].health = 0.0
    supply.run_supply(gulf, D)
    assert gulf.ground_units["ir_84div"].supply < 1.0 and gulf.ground_units["us1bct"].supply == 1.0


def test_readiness_and_grounding(gulf):
    st, sq = gulf, gulf.squadrons["77fs"]
    assert readiness.readiness(st, sq, D) == (18, "")
    st.airbases["dhafra"].fuel.jet = 7
    assert readiness.readiness(st, sq, D) == (2, "fuel shortage")
    st.airbases["dhafra"].fuel.jet = 0
    assert readiness.readiness(st, sq, D)[1] == "no fuel"
    st.airbases["dhafra"].fuel.jet = 500
    st.airbases["dhafra"].munition_level = 0.0
    assert readiness.readiness(st, sq, D)[1] == "no munitions"
    st.airbases["dhafra"].munition_level = 1.0
    st.airbases["dhafra"].runway_health = 0.1
    assert readiness.readiness(st, sq, D)[1] == "runway out of action"
    st.airbases["dhafra"].runway_health = 1.0
    sq.airframes = 0
    assert readiness.squadron_status(st, sq, D)["state"] == "grounded"
    st.naval_groups["cvn73"].health = 0.1
    assert readiness.readiness(st, st.squadrons["vfa27"], D)[1] == "carrier out of action"


def test_charge_sortie(gulf):
    sq = gulf.squadrons["77fs"]
    readiness.charge_sortie(gulf, sq, 4, "STRIKE", D)
    assert gulf.airbases["dhafra"].fuel.jet == 1500 - 12
    assert gulf.airbases["dhafra"].munition_level < 1.0 and sq.sorties_flown == 4


def test_replacements_prioritise_depleted(gulf):
    st = gulf
    st.squadrons["77fs"].airframes = 4
    st.squadrons["71fs"].airframes = 16
    rep = production.replacements(st, D)
    assert rep["airframes"].get("77fs", 0) >= 2 and st.squadrons["77fs"].airframes > 4
    assert sum(rep["airframes"].get(s.id, 0) for s in st.squadrons.values() if s.coalition == "blue") == 3
    for n in st.supply_nodes.values():
        if n.coalition == "blue":
            n.health = 0.0
    before = st.squadrons["77fs"].airframes
    production.replacements(st, D)
    assert st.squadrons["77fs"].airframes == before            # no production without factories/ports


def test_repairs(gulf):
    gulf.airbases["dhafra"].runway_health = 0.2
    gulf.sam_sites["sa10_ba"].health = 0.5
    gulf.supply_nodes["dep_lar"].health = 0.4
    production.repairs(gulf, D)
    assert gulf.airbases["dhafra"].runway_health == 0.45
    assert gulf.sam_sites["sa10_ba"].health > 0.5 and gulf.supply_nodes["dep_lar"].health == 0.55


def test_airwar_is_deterministic_and_costs(gulf):
    def run():
        st = copy.deepcopy(gulf)
        tgt = Target(kind="sam_site", id="sa6_hava", name="SA-6", lat=27.15, lon=56.12)
        cap_t = Target(kind="airbase", id="bandarabbas", name="BA", lat=27.22, lon=56.38)
        ato = Ato(id="ato-1", turn=1, packages=[
            _pkg("p1", "blue", "SEAD", tgt, [_flt("f1", st, "77fs", "SEAD"), _flt("f2", st, "71fs", "ESCORT")]),
            _pkg("p2", "red", "CAP", cap_t, [_flt("f3", st, "tfb9a", "CAP")])])
        return st, airwar.resolve_ato(st, ato, D), ato
    st1, s1, ato1 = run()
    st2, s2, _ = run()
    assert s1 == s2 and st1.sam_sites["sa6_hava"].health == st2.sam_sites["sa6_hava"].health
    assert s1["blue"]["sorties"] == 8 and s1["red"]["sorties"] == 4
    assert st1.airbases["dhafra"].fuel.jet < 1500
    assert all(f.status == "resolved" for _, f in ato1.flights())
    lost = s1["blue"]["lost"]
    assert st1.squadrons["77fs"].airframes + st1.squadrons["71fs"].airframes <= 36 - lost


def test_airwar_skips_flights_flown_in_dcs(gulf):
    tgt = Target(kind="supply_node", id="dep_lar", name="Lar", lat=27.68, lon=54.34)
    ato = Ato(id="ato-1", turn=1, packages=[_pkg("p1", "blue", "STRIKE", tgt, [
        _flt("f1", gulf, "336fs", "STRIKE"), _flt("f2", gulf, "71fs", "ESCORT")])])
    airwar.resolve_ato(gulf, ato, D, skip_flights=["f1"])
    assert ato.find_flight("f1")[1].status == "planned" and ato.find_flight("f2")[1].status == "resolved"
    assert gulf.supply_nodes["dep_lar"].health == 1.0


def test_strike_damages_targets(gulf):
    rng = gulf.rng("x")
    cases = [("supply_node", "dep_lar", lambda s: s.supply_nodes["dep_lar"].health < 1),
             ("supply_route", "dep_lar__dep_lengeh", lambda s: s.supply_routes["dep_lar__dep_lengeh"].interdiction > 0),
             ("airbase", "lar", lambda s: s.airbases["lar"].runway_health < 1 and s.airbases["lar"].hit_last_turn),
             ("front", "musandam", lambda s: s.fronts["musandam"].cas_effect["blue"] > 0),
             ("naval_group", "ir_fleet", lambda s: s.naval_groups["ir_fleet"].health < 1),
             ("sam_site", "sa2_ba", lambda s: s.sam_sites["sa2_ba"].health < 1)]
    for kind, eid, check in cases:
        pkg = _pkg("p", "blue", "STRIKE", Target(kind=kind, id=eid, name=eid, lat=27, lon=55), [])
        from sortie.models_ato import FlightResult
        ok = airwar.apply_strike(gulf, pkg, _flt("f", gulf, "336fs", "STRIKE"), 4.0, FlightResult(flight_id="f"), rng)
        assert ok > 0 and check(gulf), kind


def test_front_moves_toward_weaker_side_and_captures(coldwar):
    st = coldwar
    for g in st.ground_units.values():
        if g.coalition == "blue":
            g.strength = 0.1
    f = st.fronts["hannover_axis"]
    start = f.position
    for _ in range(12):
        rep = ground.run_ground(st, D)
    assert f.position < start and f.pressure < 0 and st.meta.war_score < 0
    # push the line west of Wunstorf: the base must change hands and its squadron relocate
    f.position = 0.03
    rep = ground.run_ground(st, D)
    assert "airbase:wunstorf" in rep["captured"]
    assert st.airbases["wunstorf"].coalition == "red" and st.squadrons["480tfs"].airbase_id != "wunstorf"
    assert "supply_node:rail_hannover" in rep["captured"]


def test_axis_param(coldwar):
    f = coldwar.fronts["hannover_axis"]
    t, off = ground.axis_param(f, (f.a.lat + f.b.lat) / 2, (f.a.lon + f.b.lon) / 2)
    assert abs(t - 0.5) < 0.02 and off < 2


def test_end_turn_advances_everything(gulf):
    gulf.pilot.status = "wounded"
    rep = turn.end_turn(gulf, D)
    assert gulf.meta.turn == 2 and gulf.meta.date == "2012-03-14T11:45:00"
    assert set(rep) >= {"air", "ground", "supply", "replacements", "repairs", "war_score"}
    assert gulf.pilot.status == "active" and gulf.ato is None
    cv = gulf.naval_groups["cvn73"]
    assert (cv.lat, cv.lon) == (25.10, 57.90) and gulf.airbases["cvn73"].lat == 25.10


def test_victory_condition(gulf):
    gulf.fronts["musandam"].position = 0.98
    for g in gulf.ground_units.values():
        if g.coalition == "red":
            g.strength = 0.05
    ground.run_ground(gulf, D)
    assert gulf.meta.status == "won"
