import copy

import pytest

from sortie import config, geo, units
from sortie.ato import assign, needs, planner, radio, route
from sortie.models_ato import Target
from tests.conftest import make_state

D = config.defaults()


def _top(st, side, mission):
    return max((n for n in needs.score_needs(st, side, D) if n.mission == mission), key=lambda n: n.score)


def test_needs_have_reasons_and_are_sorted(gulf):
    ns = needs.score_needs(gulf, "blue", D)
    assert all(n.reason for n in ns)
    assert [n.score for n in ns] == sorted((n.score for n in ns), reverse=True)
    assert {"CAP", "SEAD", "STRIKE", "CAS", "INTERDICTION", "ANTISHIP", "AWACS", "TANKER", "RECON"} <= {n.mission for n in ns}


def test_sam_near_front_raises_sead(gulf):
    far, near = "sa2_kish", "sa8_front"
    ns = {n.target.id: n for n in needs.score_needs(gulf, "blue", D) if n.target.kind == "sam_site"}
    assert ns[near].score > ns[far].score and "front" in ns[near].reason


def test_lost_air_superiority_raises_cap(gulf):
    base = _top(gulf, "blue", "CAP").score
    for s in gulf.squadrons.values():
        if s.coalition == "blue" and "CAP" in s.tasks:
            s.airframes = 1
    assert needs.air_superiority(gulf, "blue") < 0.3
    assert _top(gulf, "blue", "CAP").score > base + 10


def test_airbase_attack_triggers_defensive_cap_and_intercept(gulf):
    gulf.airbases["minhad"].hit_last_turn = True
    ns = [n for n in needs.score_needs(gulf, "blue", D) if n.target.id == "minhad"]
    assert {"CAP", "INTERCEPT"} <= {n.mission for n in ns} and max(n.score for n in ns) >= 70


def test_front_pressure_raises_cas(gulf):
    base = _top(gulf, "blue", "CAS").score
    gulf.fronts["musandam"].pressure = -0.9        # red pushing blue back
    assert _top(gulf, "blue", "CAS").score > base + 20


def test_era_capabilities_respected(forager, coldwar):
    ww2 = {n.mission for side in ("blue", "red") for n in needs.score_needs(forager, side, D)}
    assert not ww2 & {"AWACS", "TANKER", "SEAD"}
    red = {n.mission for n in needs.score_needs(coldwar, "red", D)}
    assert "AWACS" not in red and "TANKER" not in red
    assert "AWACS" in {n.mission for n in needs.score_needs(coldwar, "blue", D)}


@pytest.mark.parametrize("tid", ["coldwar_1985", "forager_1944", "gulf_crisis"])
def test_generate_ato(theaters, tid):
    st = make_state(theaters, tid)
    ato = planner.generate_ato(st, D)
    for side in ("blue", "red"):
        pk = [p for p in ato.packages if p.coalition == side]
        assert len(pk) >= 4, (tid, side)
    used = {}
    for p, f in ato.flights():
        sq = st.squadrons[f.squadron_id]
        assert f.task in sq.tasks and f.coalition == p.coalition and 1 <= f.count <= 4
        assert f.waypoints[0].action == "takeoff" and f.waypoints[-1].action == "land"
        assert f.freq > 0 and f.callsign and p.reason
        etas = [w.eta_s for w in f.waypoints]
        assert etas == sorted(etas) and etas[0] >= 0
        base = st.airbases[sq.airbase_id]
        assert geo.dist_km((base.lat, base.lon), (p.target.lat, p.target.lon)) <= units.combat_radius_km(f.aircraft)
        used[sq.id] = used.get(sq.id, 0) + f.count
    assert all(n <= st.squadrons[s].available for s, n in used.items())
    assert len({p.id for p in ato.packages}) == len(ato.packages)
    if tid == "forager_1944":
        assert not ato.support["blue"]["awacs"] and not ato.support["blue"]["tankers"]
    if tid == "gulf_crisis":
        assert ato.support["blue"]["awacs"] and ato.support["blue"]["tankers"][0]["tacan"]
        assert ato.support["red"]["gci"]


def test_ato_deterministic(gulf):
    a = planner.generate_ato(copy.deepcopy(gulf), D).model_dump()
    b = planner.generate_ato(copy.deepcopy(gulf), D).model_dump()
    assert a == b


def test_grounded_squadron_gets_no_tasking(gulf):
    gulf.airbases["dhafra"].fuel.jet = 0
    ato = planner.generate_ato(gulf, D)
    assert not [f for _, f in ato.flights() if st_base(gulf, f) == "dhafra"]
    res = assign.assign_player(gulf, ato, D)
    assert res["flight_id"] is None and "standing down" in res["reason"] and "fuel" in res["reason"]


def st_base(st, f):
    return st.squadrons[f.squadron_id].airbase_id


def test_strike_package_gets_sead_and_escort(gulf):
    ato = planner.generate_ato(gulf, D)
    multi = [p for p in ato.packages if p.coalition == "blue" and len(p.flights) > 1]
    assert multi
    tasks = {f.task for p in multi for f in p.flights[1:]}
    assert tasks <= {"SEAD", "ESCORT"} and "ESCORT" in tasks


def test_player_assignment(gulf):
    ato = planner.generate_ato(gulf, D)
    res = assign.assign_player(gulf, ato, D)
    pkg, flt = ato.find_flight(res["flight_id"])
    assert flt.is_player and flt.squadron_id == "77fs" and flt.aircraft == "F-16C_50"
    assert ato.player_flight_id == flt.id and ato.player_package_id == pkg.id
    assert pkg.reason in res["reason"] and flt.task in res["reason"]
    assert sum(1 for _, f in ato.flights() if f.is_player) == 1


def test_player_assignment_respects_status_and_ownership(gulf):
    ato = planner.generate_ato(gulf, D)
    gulf.pilot.status = "wounded"
    assert assign.assign_player(gulf, ato, D)["flight_id"] is None
    gulf.pilot.status = "active"
    gulf.meta.owned_modules = ["A-10C_2"]
    res = assign.assign_player(gulf, ato, D)
    assert res["flight_id"] is None and "owned" in res["reason"]


def test_forced_tasking_when_squadron_unallocated(gulf):
    ato = planner.generate_ato(gulf, D)
    for p in ato.packages:
        p.flights = [f for f in p.flights if f.squadron_id != "77fs"]
    res = assign.assign_player(gulf, ato, D)
    assert res["flight_id"] and ato.find_flight(res["flight_id"])[1].squadron_id == "77fs"


def test_coop_slots_enlarge_player_flight(gulf):
    ato = planner.generate_ato(gulf, D)
    res = assign.assign_player(gulf, ato, D, coop_slots=4)
    assert ato.find_flight(res["flight_id"])[1].count == 4


def test_route_shapes_and_tot(gulf):
    home = gulf.airbases["dhafra"]
    tgt = Target(kind="supply_node", id="dep_lengeh", name="x", lat=26.56, lon=54.88)
    wps = route.build_route(gulf, "blue", home, tgt, "F-16C_50", "STRIKE", 3000)
    assert [w.name for w in wps] == ["DEP", "INGRESS", "IP", "TGT", "EGRESS", "RTB"]
    assert next(w for w in wps if w.name == "TGT").eta_s == 3000
    cap = route.build_route(gulf, "blue", home, tgt, "F-15C", "CAP", 100)
    assert [w.name for w in cap] == ["DEP", "STN-A", "STN-B", "RTB"] and cap[0].eta_s == 0
    assert route.profile("F4U-1D", "CAS", "ww2") == (1500.0, 420.0)
    assert route.profile("AH-64D_BLK_II", "CAS", "modern")[0] == 150
    assert route.flight_time_s(wps) > 600 and route.route_length_km(wps) > 400


def test_route_avoids_sam_when_cheap(gulf):
    home = gulf.airbases["dhafra"]
    tgt = Target(kind="supply_node", id="dep_lar", name="x", lat=27.68, lon=54.34)
    direct = [(home.lat, home.lon), (tgt.lat, tgt.lon)]
    wps = route.build_route(gulf, "blue", home, tgt, "F-15ESE", "STRIKE", 3000)
    chosen = [(w.lat, w.lon) for w in wps[:3]]
    assert route._threat(gulf, "blue", chosen) <= route._threat(gulf, "blue", direct) + 0.2


def test_radio_plan():
    blue, red = radio.RadioPlan("nato", "modern", "blue"), radio.RadioPlan("soviet", "coldwar", "red")
    assert blue.next() == 251.0 and blue.next() == 251.25 and blue.guard == 243.0
    assert 124 <= red.next() <= 149
    assert radio.RadioPlan("nato", "ww2", "blue").band == "ww2"
    assert radio.callsign("Viper", 2, "nato") == "Viper 2" and radio.callsign("201", 3, "soviet") == "221"


def test_threats_for(gulf):
    ato = planner.generate_ato(gulf, D)
    res = assign.assign_player(gulf, ato, D)
    _, flt = ato.find_flight(res["flight_id"])
    th = planner.threats_for(gulf, "blue", flt, ato)
    assert isinstance(th["sams"], list) and all(s["type"] for s in th["sams"])
