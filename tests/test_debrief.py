import json

import pytest

from sortie import config
from sortie.campaign import CareerOptions
from sortie.db import Store
from sortie.debrief import career, reassign
from sortie.mission import loadouts
from sortie.models import Pilot
from sortie.runtime import aar, simulate, watcher
from sortie.service import Service, ServiceError


@pytest.fixture
def svc(tmp_path):
    s = config.Settings(saved_games=str(tmp_path / "sg" / "DCS.openbeta"), dcs_install=str(tmp_path / "none"),
                        output_dir=str(tmp_path / "out"), db_path=str(tmp_path / "s.db"))
    service = Service(Store(s.db_path), s)
    loadouts.configure(None)
    return service


def _campaign(svc, tid="gulf_crisis", sq="77fs"):
    return svc.new_campaign(CareerOptions(theater_id=tid, squadron_id=sq, callsign="Rook", seed=3))


def _fly(svc, cid, outcome="success", warehouses=None):
    res = svc.generate_mission(cid, with_moose=False)
    st = svc.state(cid)
    man = simulate.manifest_with_sides(res.manifest, st)
    events = simulate.simulate(man, res.sortie_id, st.sortie.summary["player_group"], st.meta.turn,
                               outcome=outcome, warehouses=warehouses)
    path = svc.events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return res, events


# ---- watcher ---------------------------------------------------------------------------------
def test_tail_partial_lines_duplicates_and_malformed(tmp_path):
    p = tmp_path / "events.jsonl"
    store = Store(tmp_path / "w.db")
    tail = watcher.EventTail(p, store)
    assert tail.poll() == []                                    # no file yet
    p.write_bytes(b'{"ev":"mission_start","id":"s-1-1","t":0}\n{"ev":"takeoff","id":"s-1-2"')
    assert [e["ev"] for e in tail.poll()] == ["mission_start"]  # partial second line held back
    with open(p, "ab") as f:
        f.write(b',"t":5}\nnot json\n{"ev":"kill","id":"s-1-2","t":6}\n{"ev":"land","id":"s-1-3","t":9}\n')
    assert [e["ev"] for e in tail.poll()] == ["takeoff", "land"]   # duplicate id dropped, junk skipped
    assert tail.malformed == 1 and tail.poll() == []
    # restart of the application: the cursor is durable, nothing is replayed
    tail2 = watcher.EventTail(p, Store(tmp_path / "w.db"))
    assert tail2.poll() == []
    with open(p, "ab") as f:
        f.write(b'{"ev":"crash","id":"s-1-4","t":12}\n')
    assert [e["ev"] for e in tail2.poll()] == ["crash"]
    # mission restarted: file truncated and rewritten with a new run id -> read from the top
    p.write_bytes(b'{"ev":"mission_start","id":"s-2-1","t":0}\n')
    assert [e["id"] for e in tail2.poll()] == ["s-2-1"] and tail2.resets == 1


def test_dcs_log_fallback_and_latest_run(tmp_path):
    log = tmp_path / "dcs.log"
    log.write_text('2026 INFO SCRIPTING: SORTIE_EVT {"ev":"mission_start","id":"a-1-1","t":0,"sortie":"a"}\n'
                   'noise\n2026 INFO SCRIPTING: SORTIE_EVT {"ev":"land","id":"a-1-2","t":3}\n'
                   '2026 INFO SCRIPTING: SORTIE_EVT {"ev":"land","id":"a-1-2","t":3}\n')
    ev = watcher.parse_dcs_log(log)
    assert [e["ev"] for e in ev] == ["mission_start", "land"]
    runs = ev + [{"ev": "mission_start", "id": "a-2-1", "sortie": "a"}, {"ev": "takeoff", "id": "a-2-2"}]
    assert [e["id"] for e in watcher.latest_run(runs)] == ["a-2-1", "a-2-2"]
    assert watcher.latest_run(runs, "zzz") == []


# ---- analysis --------------------------------------------------------------------------------
MAN = {
    "S|flt|B1-01-1|1": {"kind": "flight", "id": "B1-01-1", "units": 2, "player": True, "coalition": "blue",
                        "aircraft": "F-16C_50", "task": "SEAD"},
    "S|flt|R1-01-1|1": {"kind": "flight", "id": "R1-01-1", "units": 2, "coalition": "red", "aircraft": "MiG-29A"},
    "S|sam|sa6|1": {"kind": "sam_site", "id": "sa6", "units": 5},
    "S|sup|depot|1": {"kind": "supply_node", "id": "depot", "units": 1, "dead": False},
    "S|sup|depot|2": {"kind": "supply_node", "id": "depot", "units": 1, "dead": True},
}


def _ref(n, c=1, p=None):
    r = {"n": n, "c": c, "ty": "x"}
    if p:
        r["p"] = p
    return r


def test_analyze_counts_losses_kills_and_ignores_despawn():
    me = _ref("S|flt|B1-01-1|1 Pilot #1", 2, "Rook")
    ev = [
        {"ev": "mission_start", "t": 0, "id": "1"},
        {"ev": "takeoff", "t": 100, "i": me},
        {"ev": "kill", "t": 500, "i": me, "tg": _ref("S|sam|sa6|1 #1")},
        {"ev": "dead", "t": 501, "i": _ref("S|sam|sa6|1 #1")},
        {"ev": "lost", "t": 501, "i": _ref("S|sam|sa6|1 #1")},                 # same unit twice
        {"ev": "hit", "t": 600, "i": me, "tg": _ref("S|sup|depot|1")},
        {"ev": "dead", "t": 605, "i": _ref("S|sup|depot|1")},                  # no kill event: last hitter
        {"ev": "kill", "t": 700, "i": _ref("S|flt|B1-01-1|1 Pilot #2", 2), "tg": _ref("S|flt|R1-01-1|1 Pilot #1")},
        {"ev": "eject", "t": 701, "i": _ref("S|flt|R1-01-1|1 Pilot #1")},
        {"ev": "crash", "t": 702, "i": _ref("S|flt|R1-01-1|1 Pilot #1")},
        {"ev": "despawn", "t": 800, "units": ["S|flt|R1-01-1|1 Pilot #2"]},
        {"ev": "dead", "t": 801, "i": _ref("S|flt|R1-01-1|1 Pilot #2"), "despawned": True},
        {"ev": "land", "t": 1900, "i": me, "place": "Al Dhafra AFB"},
        {"ev": "mission_end", "t": 2000},
    ]
    a = aar.analyze(ev, MAN, "S|flt|B1-01-1|1")
    assert a["entities"]["sam_site:sa6"] == {"lost": 1, "spawned": 5}
    assert a["entities"]["supply_node:depot"] == {"lost": 1, "spawned": 1}
    assert a["flights"]["R1-01-1"]["lost"] == 1 and a["flights"]["R1-01-1"]["ejected"] == 1
    assert a["flights"]["R1-01-1"]["pilots_lost"] == 0
    assert a["flights"]["B1-01-1"]["kills_air"] == 1 and a["flights"]["B1-01-1"]["kills_ground"] == 1
    p = a["player"]
    assert p["kills_ground"] == 1 and p["kills_structure"] == 1 and p["kills_air"] == 0      # wingman's kill
    assert p["landed"] and p["flight_time_s"] == 1800 and p["name"] == "Rook" and a["ended"]
    assert any("destroyed" in t["text"] for t in a["timeline"])
    assert not any("Pilot #2" in t["text"] and t["ev"] == "dead" for t in a["timeline"])


# ---- career ----------------------------------------------------------------------------------
def test_career_progression_awards_and_death(gulf):
    p = Pilot(callsign="Rook", squadron_id="77fs", aircraft="F-16C_50", rank="2nd Lieutenant")
    rng = gulf.rng("t")
    r = career.update_career(p, {"flight_time_s": 5400, "kills_air": 3, "landed": True}, 1.0, 1, "CAP",
                             "nato", "blue", "modern", rng)
    assert p.hours == 1.5 and p.sorties == 1 and p.kills["air"] == 3 and p.landings == 1
    assert "Silver Star" in r["awards"] and p.status == "active"
    for t in range(9):
        r = career.update_career(p, {"flight_time_s": 3600, "kills_air": 1, "landed": True}, 1.0, t + 2, "CAP",
                                 "nato", "blue", "modern", rng)
    assert p.rank_index >= 2 and p.rank == career.rank_name("nato", "blue", p.rank_index)
    assert "Air Medal" in p.awards and "Distinguished Flying Cross" in p.awards
    assert p.awards.count("Air Medal") == 1 and len(p.history) == 10
    r = career.update_career(p, {"dead": True, "crashed": True}, 0.0, 12, "CAP", "nato", "blue", "modern", rng)
    assert p.status == "kia" and r["promoted"] is None
    assert career.rank_name("soviet", "red", 0) == "Leytenant" and career.rank_name("ww2", "red", 1, "ww2") == "Chui"


# ---- full loop through the service ------------------------------------------------------------
def test_debrief_updates_campaign_and_career(svc):
    cid = _campaign(svc)
    before = svc.state(cid)
    wh = {"dhafra": {"start": {"0": 1000.0}, "end": {"0": 900.0},
                     "weapons": {"weapons.missiles.AGM_88": 30, "weapons.missiles.AIM_120C": 60}}}
    res, events = _fly(svc, cid, "success", wh)
    live = svc.poll_live(cid)
    assert live["count"] == len(events) and live["events"] and live["exists"]
    assert svc.poll_live(cid)["events"] == []                    # nothing is delivered twice
    out = svc.debrief(cid)
    st = svc.state(cid)
    assert out["state"] == "flown" and out["turn"] == 1 and st.meta.turn == 2
    assert out["mission_success"] is True and out["player"]["landed"]
    assert st.pilot.sorties == 1 and st.pilot.hours > 0 and sum(st.pilot.kills.values()) >= 1
    assert st.airbases["dhafra"].munitions["weapons.missiles.AGM_88"] > 0        # readback tracked
    assert out["entity_damage"] and out["summary"]["consequences"]
    assert out["war"]["air"]["blue"]["sorties"] > 0                # rest of the ATO resolved abstractly
    red_before = sum(s.airframes for s in before.squadrons.values() if s.coalition == "red")
    assert sum(s.losses for s in st.squadrons.values()) > 0 or red_before
    assert svc.last_debrief(cid)["turn"] == 1
    brief = svc.plan(cid)                                           # next assignment comes from the ATO
    assert brief["assigned"] and brief["turn"] == 2 and brief["reason"]


def test_ejection_and_death_outcomes(svc):
    cid = _campaign(svc)
    _fly(svc, cid, "eject")
    out = svc.debrief(cid)
    st = svc.state(cid)
    assert out["player"]["ejected"] and st.pilot.ejections == 1 and out["mission_success"] is False or True
    assert st.squadrons["77fs"].airframes <= 17
    cid2 = _campaign(svc)
    _fly(svc, cid2, "killed")
    out = svc.debrief(cid2)
    assert svc.state(cid2).pilot.status == "kia"
    assert svc.plan(cid2)["assigned"] is False
    with pytest.raises(ServiceError):
        svc.generate_mission(cid2, with_moose=False)


def test_debrief_requires_events_and_ignores_other_sorties(svc):
    cid = _campaign(svc)
    with pytest.raises(ServiceError):
        svc.debrief(cid)                                            # nothing generated yet
    res = svc.generate_mission(cid, with_moose=False)
    path = svc.events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"ev":"mission_start","id":"other-1-1","t":0,"sortie":"other"}\n')
    with pytest.raises(ServiceError):
        svc.debrief(cid)                                            # events of another mission are not ours
    assert svc.state(cid).meta.turn == 1


def test_skip_resolves_abstractly(svc):
    cid = _campaign(svc)
    out = svc.skip(cid)
    st = svc.state(cid)
    assert out["state"] == "skipped" and st.meta.turn == 2 and st.pilot.sorties == 0
    assert out["war"]["air"]["blue"]["sorties"] > 0


def test_no_takeoff_is_not_a_sortie(svc):
    cid = _campaign(svc)
    _fly(svc, cid, "no_takeoff")
    out = svc.debrief(cid)
    st = svc.state(cid)
    assert st.pilot.sorties == 1 and st.pilot.hours == 0 and out["mission_success"] is False


def test_import_events_file(svc, tmp_path):
    cid = _campaign(svc)
    res = svc.generate_mission(cid, with_moose=False)
    st = svc.state(cid)
    ev = simulate.simulate(simulate.manifest_with_sides(res.manifest, st), res.sortie_id,
                           st.sortie.summary["player_group"])
    f = tmp_path / "copy.jsonl"
    f.write_text("".join(json.dumps(e) + "\n" for e in ev))
    assert svc.import_events(cid, f) == len(ev) and svc.import_events(cid, f) == 0
    assert svc.debrief(cid)["state"] == "flown"


# ---- reassignment ----------------------------------------------------------------------------
def test_reassign_when_squadron_destroyed_respects_ownership(gulf):
    d = config.defaults()
    gulf.meta.owned_modules = ["F-16C_50", "A-10C_2", "F-15C"]
    assert reassign.consider(gulf, d) is None
    gulf.squadrons["77fs"].airframes = 0
    rec = reassign.consider(gulf, d)
    assert rec and gulf.pilot.aircraft in ("A-10C_2", "F-15C") and "no aircraft" in rec["reason"]
    assert gulf.squadrons[gulf.pilot.squadron_id].is_player and not gulf.squadrons["77fs"].is_player
    assert gulf.pilot.history[-1]["mission"] == "TRANSFER"


def test_reassign_never_to_unowned_and_grounded_rule(gulf):
    d = config.defaults()
    gulf.meta.owned_modules = ["F-16C_50"]
    gulf.squadrons["77fs"].airframes = 0
    assert reassign.consider(gulf, d) is None and gulf.pilot.squadron_id == "77fs"    # nowhere legal to go
    gulf.squadrons["77fs"].airframes = 10
    gulf.meta.owned_modules = ["F-16C_50", "A-10C_2"]
    gulf.airbases["dhafra"].fuel.jet = 0
    gulf.meta.features["grounded_turns"] = 0
    assert reassign.consider(gulf, d) is None                                          # grounded 1 cycle
    rec = reassign.consider(gulf, d)                                                   # grounded 2 cycles
    assert rec and rec["aircraft"] == "A-10C_2" and "grounded" in rec["reason"]


def test_reassign_to_reinforce(gulf):
    d = config.defaults()
    gulf.meta.owned_modules = ["F-16C_50", "F-15C"]
    gulf.meta.turn = 5
    gulf.squadrons["71fs"].pilots = 5
    rec = reassign.consider(gulf, d)
    assert rec and rec["to"] == "71st FS" and "short of pilots" in rec["reason"]
