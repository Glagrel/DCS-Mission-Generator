"""Mission clock, real take-offs, concurrency cap, carrier support, co-op seats in other
flights, server copy, units toggle, kneeboards."""
import json
import zipfile
from datetime import timedelta

import dcs
import pytest

from sortie import config, measure
from sortie.ato import assign, planner
from sortie.campaign import CareerOptions
from sortie.db import Store
from sortie.mission import budget, builder, clock, kneeboard, loadouts, slots
from sortie.models_ato import Flight, Waypoint
from sortie.runtime import aar, simulate
from sortie.service import Service
from tests.conftest import make_state

D = config.defaults()


def _settings(tmp_path, **kw):
    return config.Settings(saved_games=str(tmp_path / "sg" / "DCS.openbeta"), dcs_install=str(tmp_path / "none"),
                           output_dir=str(tmp_path / "out"), db_path=str(tmp_path / "s.db"), **kw)


def _build(theaters, tmp_path, tid="gulf_crisis", squadron=None, **kw):
    s = _settings(tmp_path, **kw)
    loadouts.configure(None)
    st = make_state(theaters, tid, squadron=squadron, settings=s)
    ato = planner.generate_ato(st, D)
    r = assign.assign_player(st, ato, D, s.coop_slots)
    return st, ato, builder.build_mission(st, ato, r["reason"], s, with_moose=False), s


def _flight_groups(m):
    out = {}
    for side in ("blue", "red"):
        for c in m.coalition[side].countries.values():
            for g in c.plane_group + c.helicopter_group:
                out[g.name] = g
    return out


# ---- clock ---------------------------------------------------------------------------------------
def _flt(etas, names=None, hold=0.0):
    names = names or ["DEP", "INGRESS", "TGT", "RTB"]
    wps = [Waypoint(name=n, lat=25 + i * 0.5, lon=55, alt_m=0 if n in ("DEP", "RTB") else 6000,
                    speed_kmh=0 if n in ("DEP", "RTB") else 800, eta_s=e,
                    action="orbit" if n == "STN-A" else "fly", hold_s=hold if n == "STN-A" else 0)
           for i, (n, e) in enumerate(zip(names, etas))]
    return Flight(id="f", squadron_id="s", coalition="blue", aircraft="F-15C", count=2, task="CAP", waypoints=wps)


def test_phases_and_air_state():
    f = _flt([1000, 1600, 2200, 3000])
    assert clock.phase(f, 500) == clock.GROUND and clock.phase(f, 1500) == clock.AIRBORNE
    assert clock.phase(f, 3000) == clock.DONE
    s = clock.air_state(f, 1900)                         # halfway INGRESS -> TGT
    assert s.next_index == 2 and abs(s.lat - 25.75) < 0.01 and s.alt_m == 6000 and not s.on_station
    climb = clock.air_state(f, 1100)
    assert climb.next_index == 1 and 600 <= climb.alt_m < 6000
    assert clock.start_delay(f, 400, D) == 300 and clock.start_delay(f, 900, D) == 0
    assert clock.rel(1600, 1000) == 600 and clock.rel(500, 1000) == 0


def test_orbit_flight_on_station_at_start():
    f = _flt([0, 600, 700, 9000], names=["DEP", "STN-A", "STN-B", "RTB"], hold=7000)
    end = clock.station_end(f)
    assert 7000 < end < 9000
    s = clock.air_state(f, 3000)
    assert s.on_station and s.next_index == 2 and abs(s.hold_s - (end - 3000)) < 1
    assert not clock.air_state(f, 300).on_station       # still in transit


def test_support_stays_up_all_cycle(gulf):
    ato = planner.generate_ato(gulf, D)
    turn_s = gulf.meta.turn_hours * 3600
    for p, f in ato.flights():
        if f.task in ("AWACS", "TANKER", "SAR"):
            dep, end = clock.window(f)
            assert end - dep > turn_s * 0.75, f.task
            assert f.waypoints[1].hold_s > 0
        if f.task == "CAP":
            assert f.waypoints[1].hold_s == 3600


def test_mission_starts_at_player_startup(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path)
    _, flt = ato.find_flight(ato.player_flight_id)
    t0 = res.stats["t0_s"]
    assert t0 == round(flt.waypoints[0].eta_s - 600) and t0 > 0
    m = dcs.Mission()
    m.load_file(res.path)
    assert m.start_time.replace(tzinfo=None) == st.now + timedelta(seconds=clock.mission_t0(ato, D))
    assert res.briefing["mission_start"] != st.now.strftime("%H:%M:%S")
    player = _flight_groups(m)[budget.gname("flt", flt.id)]
    assert player.points[0].type == "TakeOffParking" and player.uncontrolled is False


# ---- nothing pops in: airborne at start or a real take-off ------------------------------------------
def test_flights_are_airborne_at_start_or_take_off(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path)
    m = dcs.Mission()
    m.load_file(res.path)
    groups = _flight_groups(m)
    seen = {"ground": 0, "airborne": 0, "delayed": 0}
    for name, v in res.manifest.items():
        if v["kind"] != "flight":
            continue
        g = groups[name]
        assert g.points[-1].type == "Land", name                       # everyone has a landing
        if v["phase"] == "airborne":
            assert g.points[0].type == "Turning Point" and g.start_time == 0, name   # there from second zero
            seen["airborne"] += 1
        else:
            assert g.points[0].type.startswith("TakeOff"), name        # starts on the ramp/deck
            assert g.start_time == 0, name
            seen["ground"] += 1
            if v["shared_stand"]:
                assert g.late_activation is True, name                 # appears parked once the stand is free
            elif v["start_delay_s"] > 30:
                assert g.uncontrolled is True, name                    # parked until its start-up time
                seen["delayed"] += 1
    assert seen["ground"] > 1 and seen["airborne"] > 0 and seen["delayed"] > 0
    with zipfile.ZipFile(res.path) as z:
        assert "c_time_after" in z.read("mission").decode()


def test_awacs_and_tankers_are_in_the_mission(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path)
    tasks = [v["task"] for v in res.manifest.values() if v["kind"] == "flight" and v["coalition"] == "blue"]
    assert "AWACS" in tasks and "TANKER" in tasks
    m = dcs.Mission()
    m.load_file(res.path)
    groups = _flight_groups(m)
    for name, v in res.manifest.items():
        if v["kind"] == "flight" and v["task"] in ("AWACS", "TANKER") and not v.get("role"):
            g = groups[name]
            kinds = [type(t).__name__ for p in g.points for t in p.tasks]
            assert "ControlledTask" in kinds or "OrbitAction" in kinds, name
            assert g.task in ("AWACS", "Refueling")


# ---- the limit is on aircraft airborne at once ---------------------------------------------------------
def test_limit_caps_concurrency_not_total(gulf):
    ato = planner.generate_ato(gulf, D)
    assign.assign_player(gulf, ato, D)
    t0 = clock.mission_t0(ato, D)
    lim = dict(config.profile_limits("standard"), max_air=16)
    sel = budget.select(gulf, ato, lim, t0)
    assert sel.aircraft <= 16 or sel.aircraft == sum(
        f.count for f in ato.find_flight(ato.player_flight_id)[0].flights)
    wide = budget.select(gulf, ato, dict(lim, max_air=400), t0)
    assert wide.total_aircraft >= sel.total_aircraft and not wide.dropped.get("flights")
    assert budget._peak([(0, 100, 4), (100, 200, 4), (50, 150, 2)], 0, 200) == 6
    assert budget._peak([(0, 100, 4), (100, 200, 4)], 0, 200) == 4       # back-to-back flights do not add up


# ---- carrier flight operations ------------------------------------------------------------------------
def test_carrier_has_plane_guard_and_recovery_tanker(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path, squadron="vfa27")
    roles = {v.get("role"): (n, v) for n, v in res.manifest.items() if v.get("role") and v.get("base") == "cvn73"}
    assert {"plane_guard", "recovery_tanker"} <= set(roles)
    name, helo = roles["plane_guard"]
    assert helo["aircraft"] == "SH-60B" and helo["phase"] == "airborne"
    tname, tanker = roles["recovery_tanker"]
    assert tanker["aircraft"] == "S-3B Tanker"
    m = dcs.Mission()
    m.load_file(res.path)
    groups = _flight_groups(m)
    ship = m.find_group(budget.gname("nav", "cvn73"))
    kinds = [type(t).__name__ for t in groups[tname].points[0].tasks]
    assert "RecoveryTanker" in kinds
    sx, sy = ship.position.x, ship.position.y
    hx, hy = groups[name].units[0].position.x, groups[name].units[0].position.y
    assert 1000 < ((hx - sx) ** 2 + (hy - sy) ** 2) ** 0.5 < 3000       # ~1 nm off the starboard side
    assert groups[name].units[0].alt < 200
    with zipfile.ZipFile(res.path) as z:
        cfg = z.read("l10n/DEFAULT/sortie_config.lua").decode()
        assert "sortie_carrier.lua" in res.scripts and '["role"] = "plane_guard"' in cfg
    tk = [t for t in res.briefing["tankers"] if t.get("recovery")]
    assert tk


def test_no_carrier_support_in_ww2(forager):
    ato = planner.generate_ato(forager, D)
    assert not [f for _, f in ato.flights() if f.task in ("SAR", "TANKER", "AWACS")]


# ---- co-op: friends in their own aircraft ---------------------------------------------------------------
def test_extra_pilots_get_seats_in_other_flights(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path, coop_slots=2, coop_extra_slots=3)
    assert res.stats["multiplayer"] and res.stats["human_seats"] == 5
    career = [s for s in res.slots if s["career"]]
    guests = [s for s in res.slots if not s["career"]]
    assert len(career) == 1 and career[0]["positions"] == [1, 2]
    assert sum(s["seats"] for s in guests) == 3 and all(1 not in s["positions"] for s in guests)  # AI keeps the lead
    m = dcs.Mission()
    m.load_file(res.path)
    groups = _flight_groups(m)
    clients = 0
    for s in res.slots:
        g = groups[s["group"]]
        skills = [u.skill.value for u in g.units]
        assert "Player" not in skills
        assert [i + 1 for i, k in enumerate(skills) if k == "Client"] == s["positions"]
        assert g.points[0].type == "TakeOffParking"                     # cold on the ramp, never air-start
        clients += len(s["positions"])
        assert res.manifest[s["group"]]["clients"] == [g.units[i - 1].name for i in s["positions"]]
    assert clients == 5
    everyone = [u.skill.value for g in groups.values() for u in g.units]
    assert everyone.count("Client") == 5
    assert "CO-OP SLOTS" in m.description_text()
    with zipfile.ZipFile(res.path) as z:
        cfg = z.read("l10n/DEFAULT/sortie_config.lua").decode()
    assert all(s["group"] in cfg.split('["client_groups"]')[1].split("}")[0] for s in res.slots)


def test_guest_modules_are_restricted(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path, coop_extra_slots=4, coop_modules=["A-10C_2"])
    guests = [s for s in res.slots if not s["career"]]
    assert all(s["aircraft"] == "A-10C_2" for s in guests)
    if sum(s["seats"] for s in guests) < 4:
        assert any("extra co-op seats could not be placed" in w for w in res.warnings)
    st, ato, res, _ = _build(theaters, tmp_path / "b", coop_extra_slots=2, coop_modules=[])
    assert [s for s in res.slots if not s["career"]] == []
    assert any("could not be placed" in w for w in res.warnings)


def test_single_player_unchanged(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path)
    assert not res.stats["multiplayer"] and res.stats["human_seats"] == 1 and len(res.slots) == 1
    assert slots.is_multiplayer(1, 0) is False and slots.is_multiplayer(1, 1) and slots.is_multiplayer(2, 0)


def _ref(n, c=2, p=None, ty="F-16C_50"):
    r = {"n": n, "c": c, "ty": ty}
    if p:
        r["p"] = p
    return r


def test_guests_are_tracked_and_unused_seats_cost_nothing(tmp_path):
    svc = Service(Store(str(tmp_path / "s.db")), _settings(tmp_path, coop_slots=2, coop_extra_slots=2))
    loadouts.configure(None)
    cid = svc.new_campaign(CareerOptions(theater_id="gulf_crisis", squadron_id="77fs", callsign="Rook", seed=3))
    res = svc.generate_mission(cid, with_moose=False)
    st = svc.state(cid)
    guest = next(s for s in res.slots if not s["career"])
    me = next(s for s in res.slots if s["career"])
    gunit = res.manifest[guest["group"]]["clients"][0]
    lead, wing = res.manifest[me["group"]]["clients"]
    sid = res.sortie_id
    target = next(n for n, v in res.manifest.items() if v["kind"] == "sam_site")
    ev = [
        {"ev": "mission_start", "t": 0, "id": f"{sid}-1-1", "sortie": sid},
        {"ev": "birth", "t": 1, "id": f"{sid}-1-2", "i": _ref(lead, p="Rook")},
        {"ev": "birth", "t": 30, "id": f"{sid}-1-3", "i": _ref(gunit, p="Goose", ty=guest["aircraft"])},
        {"ev": "takeoff", "t": 600, "id": f"{sid}-1-4", "i": _ref(lead, p="Rook")},
        {"ev": "takeoff", "t": 700, "id": f"{sid}-1-5", "i": _ref(gunit, p="Goose")},
        {"ev": "kill", "t": 2000, "id": f"{sid}-1-6", "i": _ref(gunit, p="Goose"), "tg": _ref(target + " #1", 1)},
        {"ev": "dead", "t": 2001, "id": f"{sid}-1-7", "i": _ref(target + " #1", 1)},
        {"ev": "eject", "t": 2500, "id": f"{sid}-1-8", "i": _ref(gunit, p="Goose")},
        {"ev": "crash", "t": 2510, "id": f"{sid}-1-9", "i": _ref(gunit, p="Goose")},
        {"ev": "land", "t": 4200, "id": f"{sid}-1-10", "i": _ref(lead, p="Rook")},
        {"ev": "mission_end", "t": 4300, "id": f"{sid}-1-11"},
    ]
    facts = aar.analyze(ev, res.manifest, st.sortie.summary["player_group"])
    humans = {h["name"]: h for h in facts["humans"]}
    assert set(humans) == {"Rook", "Goose"}                              # the empty wingman seat is not a pilot
    assert humans["Goose"]["kills_ground"] == 1 and humans["Goose"]["ejected"] and not humans["Goose"]["landed"]
    assert humans["Rook"]["landed"] and humans["Rook"]["flight_time_s"] == 3600
    assert facts["flights"][me["flight_id"]]["absent"] == 1              # seat 2 of my flight was never taken
    assert facts["flights"][guest["flight_id"]]["lost"] == 1
    gsq = st.squadrons[st.ato.find_flight(guest["flight_id"])[1].squadron_id]
    before = gsq.airframes
    p = svc.events_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(e) + "\n" for e in ev))
    deb = svc.debrief(cid)
    after = svc.state(cid)
    assert len(deb["summary"]["humans"]) == 2
    assert deb["flights"][guest["flight_id"]]["lost"] == 1 and deb["flights"][guest["flight_id"]]["kills_ground"] == 1
    # the guest's aircraft came out of that squadron's inventory (minus any replacement that cycle)
    assert after.squadrons[gsq.id].losses >= 1 and after.squadrons[gsq.id].airframes <= before
    assert after.pilot.sorties == 1 and after.pilot.kills["ground"] == 0      # career = seat 1 only


# ---- dedicated server -------------------------------------------------------------------------------------
def test_server_copy_and_event_sources(theaters, tmp_path):
    srv = tmp_path / "sg" / "DCS.server1"
    st, ato, res, s = _build(theaters, tmp_path, server_saved_games=str(srv), save_to_server=True)
    copy = srv / "Missions" / "SORTIE" / res.filename
    assert res.extra_paths == [str(copy)] and copy.is_file()
    assert copy.read_bytes() == (tmp_path / "out" / res.filename).read_bytes()
    cands = config.event_file_candidates(s)
    assert cands[0] == tmp_path / "sg" / "DCS.openbeta" / "Missions" / "SORTIE" / "runtime" / "events.jsonl"
    assert cands[1] == srv / "Missions" / "SORTIE" / "runtime" / "events.jsonl"
    off = _settings(tmp_path / "x", server_saved_games=str(srv))
    assert config.server_output_dir(off) is None                       # folder set but option off


def test_events_are_read_from_the_server_folder(tmp_path):
    srv = tmp_path / "sg" / "DCS.server1"
    svc = Service(Store(str(tmp_path / "s.db")), _settings(tmp_path, server_saved_games=str(srv), save_to_server=True))
    loadouts.configure(None)
    cid = svc.new_campaign(CareerOptions(theater_id="gulf_crisis", squadron_id="77fs", callsign="Rook", seed=3))
    res = svc.generate_mission(cid, with_moose=False)
    st = svc.state(cid)
    ev = simulate.simulate(simulate.manifest_with_sides(res.manifest, st), res.sortie_id,
                           st.sortie.summary["player_group"])
    f = srv / "Missions" / "SORTIE" / "runtime" / "events.jsonl"       # the server wrote the file, not the client
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(e) + "\n" for e in ev))
    live = svc.poll_live(cid)
    assert live["count"] == len(ev) and live["file"] == str(f) and len(live["watching"]) >= 2
    assert svc.debrief(cid)["state"] == "flown"


# ---- units --------------------------------------------------------------------------------------------------
def test_units_toggle(theaters, tmp_path):
    assert measure.alt(6096, "imperial") == "20,000 ft" and measure.alt(6096, "metric") == "6 100 m"
    assert measure.speed(926, "imperial") == "500 kt" and measure.speed(926, "metric") == "926 km/h"
    assert measure.dist(185.2, "imperial") == "100 nm" and measure.dist(185.2, "metric") == "185 km"
    assert measure.wind(270, 5, "imperial") == "270/10 kt" and measure.norm("bogus") == "imperial"
    assert measure.ddm(25.5, -55.25) == ("N25 30.000", "W055 15.000")
    _, _, imp, _ = _build(theaters, tmp_path / "i", units="imperial")
    _, _, met, _ = _build(theaters, tmp_path / "m", units="metric")
    assert imp.briefing["waypoints"][1]["alt"].endswith(" ft") and imp.briefing["waypoints"][1]["speed"].endswith(" kt")
    assert met.briefing["waypoints"][1]["alt"].endswith(" m") and met.briefing["waypoints"][1]["speed"].endswith("km/h")
    assert "nm" in imp.briefing["target"]["bullseye"] and "km" in met.briefing["target"]["bullseye"]


# ---- kneeboard ----------------------------------------------------------------------------------------------
def test_kneeboard_pages_in_mission(theaters, tmp_path):
    from PIL import Image
    import io
    st, ato, res, _ = _build(theaters, tmp_path, coop_extra_slots=2)
    types = {s["aircraft"] for s in res.slots}
    with zipfile.ZipFile(res.path) as z:
        names = [n for n in z.namelist() if n.startswith("KNEEBOARD/")]
        assert res.stats["kneeboard_pages"] == len(names) >= 2
        for t in types:
            assert f"KNEEBOARD/{t}/IMAGES/SORTIE_01_flight.png" in names
            assert f"KNEEBOARD/{t}/IMAGES/SORTIE_90_support.png" in names
        assert not [n for n in names if "//" in n]
        img = Image.open(io.BytesIO(z.read(names[0])))
        assert img.size == (768, 1024) and img.format == "PNG"
        assert len(set(img.convert("L").getdata())) > 2                 # something is drawn on it
    dcs.Mission().load_file(res.path)                                   # extra files do not break loading


def test_kneeboard_failure_does_not_stop_the_build(theaters, tmp_path, monkeypatch):
    monkeypatch.setattr(kneeboard, "pages", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no font")))
    st, ato, res, _ = _build(theaters, tmp_path)
    assert res.ok and res.stats["kneeboard_pages"] == 0
    assert any("Kneeboard pages could not be generated" in w for w in res.warnings)


# ---- combat before launch is resolved before the mission is built ------------------------------------------
def test_packages_finished_before_launch_are_resolved_first(tmp_path):
    svc = Service(Store(str(tmp_path / "s.db")), _settings(tmp_path))
    loadouts.configure(None)
    cid = svc.new_campaign(CareerOptions(theater_id="gulf_crisis", squadron_id="77fs", callsign="Rook", seed=3))
    svc.plan(cid)
    st = svc.state(cid)
    pkg, flt = st.ato.find_flight(st.ato.player_flight_id)
    early = next(p for p in st.ato.packages if p.id != pkg.id and p.coalition == "blue" and p.mission == "STRIKE")
    shift = max(f.waypoints[-1].eta_s for f in early.flights) + 600
    for w in flt.waypoints:                                              # make the player launch after it lands
        w.eta_s += shift
    from sortie.state import save_state
    save_state(svc.store, cid, st)
    res = svc.generate_mission(cid, with_moose=False)
    st = svc.state(cid)
    assert all(f.status == "resolved" for f in st.ato.find_flight(early.flights[0].id)[0].flights)
    assert not [n for n, v in res.manifest.items() if v["kind"] == "flight" and v["id"] == early.flights[0].id]
    assert any(early.id in line for line in res.briefing["pre_mission"])
    again = svc.generate_mission(cid, with_moose=False)                 # regenerating does not fight it twice
    assert again.briefing["pre_mission"] == res.briefing["pre_mission"]


# ---- support on station for the whole ATO, join point, hot start, re-planning --------------------------
def test_support_on_station_from_cycle_start_until_last_landing(gulf):
    ato = planner.generate_ato(gulf, D)
    cycle = gulf.meta.turn_hours * 3600
    for side in ("blue", "red"):
        mine = [f for p in ato.packages if p.coalition == side for f in p.flights]
        last = max(clock.window(f)[1] for f in mine if f.task not in ("AWACS", "TANKER", "SAR"))
        support = [f for f in mine if f.task in ("AWACS", "TANKER", "SAR")]
        if side == "blue":
            assert {"AWACS", "TANKER", "SAR"} <= {f.task for f in support}
        for f in support:
            on = f.waypoints[1].eta_s
            off = clock.station_end(f)
            assert on == 0 and clock.window(f)[0] < 0            # already up when the cycle begins
            assert off >= last + 899 and off >= cycle             # stays until everyone is down / next cycle
            for t0 in (0.0, 1800.0, last, cycle - 1):             # whenever the mission starts, it is on station
                assert clock.phase(f, t0) == clock.AIRBORNE and clock.air_state(f, t0).on_station


def test_support_in_mission_whatever_the_player_time(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path)
    m = dcs.Mission()
    m.load_file(res.path)
    groups = _flight_groups(m)
    seen = set()
    for name, v in res.manifest.items():
        if v["kind"] == "flight" and v["coalition"] == "blue" and v["task"] in ("AWACS", "TANKER"):
            g = groups[name]
            assert g.points[0].type == "Turning Point" and g.start_time == 0 and not g.late_activation
            seen.add(v["task"])
    assert seen == {"AWACS", "TANKER"}


def test_stale_plan_is_replanned_until_flown(tmp_path):
    svc = Service(Store(str(tmp_path / "s.db")), _settings(tmp_path))
    loadouts.configure(None)
    cid = svc.new_campaign(CareerOptions(theater_id="gulf_crisis", squadron_id="77fs", callsign="Rook", seed=3))
    svc.plan(cid)
    st = svc.state(cid)
    st.ato.version = 1                                            # as saved by an older SORTIE
    for _, f in st.ato.flights():
        if f.task == "AWACS":
            f.waypoints[-1].eta_s = 1400.0                        # the old bug: "lands" before the player launches
    from sortie.state import save_state
    save_state(svc.store, cid, st)
    svc.plan(cid)
    fresh = svc.state(cid).ato
    assert fresh.version == planner.PLAN_VERSION
    assert all(clock.window(f)[1] > 20000 for _, f in fresh.flights() if f.task == "AWACS")
    res = svc.generate_mission(cid, with_moose=False)
    assert "AWACS" in {v["task"] for v in res.manifest.values() if v["kind"] == "flight"}
    # an old plan with packages already resolved before launch is still replaced ...
    st = svc.state(cid)
    st.ato.version = 1
    next(f for _, f in st.ato.flights() if not f.is_player).status = "resolved"
    save_state(svc.store, cid, st)
    svc.plan(cid)
    assert svc.state(cid).ato.version == planner.PLAN_VERSION
    # ... but never once the sortie has been flown in DCS
    st = svc.state(cid)
    st.ato.version = 1
    next(f for _, f in st.ato.flights() if f.is_player).status = "simulated"
    save_state(svc.store, cid, st)
    svc.plan(cid)
    assert svc.state(cid).ato.version == 1


def test_hot_start_option(theaters, tmp_path):
    st, ato, cold, _ = _build(theaters, tmp_path / "c", coop_slots=2)
    st2, ato2, hot, _ = _build(theaters, tmp_path / "h", coop_slots=2, player_start="hot")
    assert cold.stats["player_start"] == "cold" and hot.stats["player_start"] == "hot"
    assert hot.stats["t0_s"] - cold.stats["t0_s"] == 7 * 60        # opens 3 min before take-off instead of 10
    for res, expected in ((cold, "TakeOffParking"), (hot, "TakeOffParkingHot")):
        m = dcs.Mission()
        m.load_file(res.path)
        groups = _flight_groups(m)
        for s in res.slots:
            assert groups[s["group"]].points[0].type == expected
            assert [u.skill.value for u in groups[s["group"]].units][:2] == ["Client", "Client"]


def test_package_join_point(gulf):
    from sortie.ato import route
    ato = planner.generate_ato(gulf, D)
    multi = [p for p in ato.packages if len(p.flights) > 1 and p.mission not in ("CAP", "AWACS", "TANKER", "SAR")]
    joined = [p for p in multi if any(w.name == "JOIN" for w in p.flights[0].waypoints)]
    assert joined and len(joined) >= len(multi) // 2
    for p in joined:
        pts = set()
        push = p.flights[0].waypoints[1].eta_s
        for f in p.flights:
            names = [w.name for w in f.waypoints]
            assert names[:3] == ["DEP", "JOIN", "INGRESS"], names
            j = f.waypoints[1]
            pts.add((round(j.lat, 4), round(j.lon, 4)))
            assert j.action == "join" and j.eta_s <= push + 1       # everyone is there by push time
            assert f.waypoints[0].eta_s >= 0 and j.eta_s > f.waypoints[0].eta_s
            etas = [w.eta_s for w in f.waypoints]
            assert etas == sorted(etas)
        assert len(pts) == 1                                        # one common point for the package
        j = p.flights[0].waypoints[1]
        assert route._friendly(gulf, p.coalition, (j.lat, j.lon))    # in friendly territory
    solo = [p for p in ato.packages if len(p.flights) == 1]
    assert all(not any(w.name == "JOIN" for w in p.flights[0].waypoints) for p in solo)


def test_join_is_never_in_enemy_territory(gulf):
    from sortie.ato import route
    sam = gulf.sam_sites["sa10_ba"]
    assert not route._friendly(gulf, "blue", (sam.lat, sam.lon))
    f = gulf.fronts["musandam"]
    assert not route._friendly(gulf, "blue", (f.b.lat, f.b.lon))    # red's end of the front axis
    assert route._friendly(gulf, "blue", (24.3, 54.6))               # over Al Dhafra


def test_escort_task_starts_at_join_and_briefing_mentions_it(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path)
    pkg, flt = ato.find_flight(ato.player_flight_id)
    if any(w.name == "JOIN" for w in flt.waypoints):
        assert res.briefing["join"] and "JOIN" in [w["name"] for w in res.briefing["waypoints"]]
    m = dcs.Mission()
    m.load_file(res.path)
    groups = _flight_groups(m)
    checked = 0
    for name, v in res.manifest.items():
        if v["kind"] == "flight" and v["task"] == "ESCORT" and v["phase"] == "ground":
            g = groups[name]
            joins = [p for p in g.points if p.name == "JOIN"]
            lead_id = ato.find_flight(v["id"])[0].flights[0].id
            lead_in_mission = budget.gname("flt", lead_id) in groups     # else pydcs's generic escort stays
            if joins and lead_in_mission:
                assert "EscortTaskAction" in [type(t).__name__ for t in joins[0].tasks]
                assert "EscortTaskAction" not in [type(t).__name__ for t in g.points[0].tasks]
                checked += 1
    assert checked >= 1


# ---- loadouts, navaids, beacons, log fallback (second flown-mission feedback) --------------------------
def _payload(*clsids, tasks=()):
    return {"name": "x", "pylons": {i + 1: {"CLSID": c, "num": i + 1} for i, c in enumerate(clsids)},
            "tasks": {i + 1: t for i, t in enumerate(tasks)}}


AIM9X, AIM120, HARM = "{5CE2FF2A-645A-4197-B48D-8720AC69394F}", "{40EF17B7-F508-45de-8566-6FFECC0C1AB8}", \
    "{B06DD79A-F21E-4EB9-BD9D-AB3844618C93}"
TANK = "{FPU_8A_FUEL_TANK}"


def test_loadout_scoring_prefers_tanks_and_self_defence():
    full = _payload(AIM9X, HARM, HARM, AIM120, TANK, AIM120, HARM, HARM, AIM9X)
    bare = _payload(HARM, HARM, HARM, HARM)
    assert loadouts.score(full, "SEAD") > loadouts.score(bare, "SEAD") + 5
    assert loadouts.score(_payload(), "SEAD") < 0                         # an empty payload never wins
    assert loadouts.score(_payload(AIM9X, AIM120, TANK), "SEAD") < 0      # nothing for the task
    assert loadouts.score(_payload(AIM9X, AIM120, AIM120, TANK), "CAP") > \
        loadouts.score(_payload(AIM9X, HARM, HARM, TANK), "CAP")


def test_pick_uses_score_and_user_named_payload(monkeypatch):
    from dcs import task as dcstask
    sead = dcstask.SEAD.id
    table = {"A bare": _payload(HARM, HARM, tasks=[sead]),
             "B full": _payload(AIM9X, HARM, HARM, TANK, AIM9X, tasks=[sead]),
             "C empty": _payload(tasks=[sead])}
    monkeypatch.setattr(loadouts, "_payloads", lambda ac: table)
    assert loadouts.pick("FA-18C_hornet", "SEAD") == "B full"          # not simply the first by name
    table["SORTIE SEAD"] = _payload(HARM, AIM9X)                        # your own payload always wins
    assert loadouts.pick("FA-18C_hornet", "SEAD") == "SORTIE SEAD"
    table.clear()
    assert loadouts.pick("FA-18C_hornet", "SEAD") == ""


def test_default_pylons_are_cleared_before_loading(theaters, tmp_path, monkeypatch):
    monkeypatch.setattr(loadouts, "pick", lambda ac, t: "x")
    monkeypatch.setattr(loadouts, "pylons", lambda ac, name: [(2, {"clsid": HARM}), (5, {"clsid": TANK})]
                        if ac == "FA-18C_hornet" else None)
    monkeypatch.setattr(loadouts, "describe", lambda ac, name: [])
    st, ato, res, _ = _build(theaters, tmp_path, squadron="vfa27")
    m = dcs.Mission()
    m.load_file(res.path)
    g = _flight_groups(m)[budget.gname("flt", ato.player_flight_id)]
    for u in g.units:
        assert sorted(u.pylons) == [2, 5]                                # nothing left over from a default


def test_weapons_unlimited_by_default_fuel_limited(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, tmp_path)
    m = dcs.Mission()
    m.load_file(res.path)
    ap = m.terrain.airports["Al Dhafra AFB"]
    assert ap.unlimited_munitions is True and ap.unlimited_fuel is False
    assert D["logistics"]["limit_munitions"] is False


def test_carrier_and_tanker_beacons(theaters, tmp_path):
    from sortie import navaids
    st, ato, res, _ = _build(theaters, tmp_path, squadron="vfa27")
    plan = navaids.carrier_plan(st)
    assert plan["cvn73"]["tacan"] == "71X" and plan["cvn73"]["icls"] == 1 and plan["lha1"]["tacan"] == "72X"
    assert len(plan["cvn73"]["ident"]) == 3
    m = dcs.Mission()
    m.load_file(res.path)
    ship = m.find_group(budget.gname("nav", "cvn73"))
    kinds = [type(t).__name__ for t in ship.points[0].tasks]
    for k in ("ActivateBeaconCommand", "ActivateICLSCommand", "ActivateLink4Command", "ActivateACLSCommand"):
        assert k in kinds, k
    beacon = next(t for t in ship.points[0].tasks if type(t).__name__ == "ActivateBeaconCommand")
    assert beacon.params["action"]["params"]["channel"] == 71
    assert beacon.params["action"]["params"]["unitId"] == ship.units[0].id
    nav = res.briefing["nav"]
    assert nav["kind"] == "carrier" and nav["tacan"].startswith("71X") and nav["icls"] == 1
    assert any("TACAN 71X" in line for line in res.briefing["nav_lines"])
    assert "TACAN 71X" in m.description_text() and "ICLS channel 1" in m.description_text()
    groups = _flight_groups(m)
    tankers = [(n, v) for n, v in res.manifest.items() if v["kind"] == "flight" and v["task"] == "TANKER"
               and v["coalition"] == "blue"]
    assert tankers
    for name, v in tankers:
        cmds = [t for t in groups[name].points[0].tasks if type(t).__name__ == "ActivateBeaconCommand"]
        assert cmds and v["tacan"]
        listed = next(t for t in res.briefing["tankers"] if t["flight_id"] == v["id"])
        assert v["tacan"].startswith(listed["tacan"])                     # same channel as briefed


def test_no_carrier_beacons_in_1944(forager):
    from sortie import navaids
    assert navaids.carrier_plan(forager) == {}


def test_parse_terrain_beacons_and_airfield_nav(tmp_path):
    from sortie import navaids, terrain
    text = """beacons = {
\t{
\t\tdisplay_name = _('');
\t\tbeaconId = 'airfield4_3';
\t\ttype = BEACON_TYPE_ILS_GLIDESLOPE;
\t\tcallsign = 'RMA';
\t\tfrequency = 108700000.000000;
\t\tchannel = 24;
\t};
\t{
\t\tdisplay_name = _('');
\t\tbeaconId = 'airfield4_5';
\t\ttype = BEACON_TYPE_ILS_LOCALIZER;
\t\tcallsign = 'RMA';
\t\tfrequency = 108700000.000000;
\t\tchannel = 24;
\t};
\t{
\t\tdisplay_name = _('AlDhafra');
\t\tbeaconId = 'airfield4_8';
\t\ttype = BEACON_TYPE_VORTAC;
\t\tcallsign = 'MA';
\t\tfrequency = 114900000.000000;
\t\tchannel = 96;
\t};
}"""
    parsed = navaids.parse_beacons(text)
    assert parsed["airfield4_8"] == {"type": "VORTAC", "callsign": "MA", "frequency_hz": 114900000.0,
                                     "channel": 96, "name": "AlDhafra"}
    assert parsed["airfield4_5"]["type"] == "ILS_LOCALIZER"
    inst = tmp_path / "DCS"
    (inst / "Mods" / "terrains" / "PersianGulf").mkdir(parents=True)
    (inst / "Mods" / "terrains" / "PersianGulf" / "beacons.lua").write_text(text)
    navaids.terrain_beacons.cache_clear()
    nav = navaids.airfield_nav(inst, "PersianGulf", terrain.new_terrain("PersianGulf").airports["Al Dhafra AFB"])
    assert nav["tacan"] == "96X MA" and nav["vor"] == "114.90 MA"
    assert nav["ils"] == [{"runway": "13R", "freq": 108.7, "ident": "RMA"}]
    assert nav["atc"]["uhf"] == 251.1
    navaids.terrain_beacons.cache_clear()
    assert navaids.airfield_nav(None, "PersianGulf", terrain.new_terrain("PersianGulf").airports["Lar"])["ils"] == []
    assert navaids.tanker_channel("31Y") == (31, "Y") and navaids.tanker_channel(None) == (None, None)


def test_debrief_reads_events_from_server_dcs_log(tmp_path):
    """Host not desanitised: events are SORTIE_EVT lines in the server's dcs.log."""
    srv = tmp_path / "sg" / "DCS.server1"
    svc = Service(Store(str(tmp_path / "s.db")), _settings(tmp_path, server_saved_games=str(srv)))
    loadouts.configure(None)
    cid = svc.new_campaign(CareerOptions(theater_id="gulf_crisis", squadron_id="77fs", callsign="Rook", seed=3))
    res = svc.generate_mission(cid, with_moose=False)
    st = svc.state(cid)
    ev = simulate.simulate(simulate.manifest_with_sides(res.manifest, st), res.sortie_id,
                           st.sortie.summary["player_group"])
    logf = srv / "Logs" / "dcs.log"
    logf.parent.mkdir(parents=True)
    logf.write_text("".join(f"2026-11-12 01:43:48.716 INFO    SCRIPTING (Main): SORTIE_EVT {json.dumps(e)}\n"
                            for e in ev) + "2026 INFO other line\n")
    assert config.dcs_log_candidates(svc.settings)[-1] == logf
    deb = svc.debrief(cid)
    assert deb["state"] == "flown" and deb["pilot"]["sorties"] == 1
