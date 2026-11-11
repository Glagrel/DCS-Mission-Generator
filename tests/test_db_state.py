from sortie import models as M
from sortie.db import Store
from sortie.models_ato import Ato, Flight, Package, Target
from sortie.state import State, load_state, save_state
from sortie import geo


def _meta():
    return M.Meta(name="t", template_id="x", terrain="PersianGulf", date="2011-06-01T06:00:00")


def test_store_roundtrip(tmp_path):
    s = Store(tmp_path / "a" / "c.db")
    s.create_campaign("c1", "Test")
    sq = M.Squadron(id="s1", name="1st", coalition="blue", country="USA", airbase_id="b", aircraft="F-15C",
                    tasks=["CAP"], airframes=12, airframes_max=12, pilots=10, pilots_max=14)
    s.put("c1", "squadron", sq)
    got = s.get("c1", "squadron", "s1", M.Squadron)
    assert got == sq and got.available == 10
    assert s.get("c1", "squadron", "zz", M.Squadron) is None
    s.log("c1", 1, "turn", {"x": 1})
    assert s.history("c1", "turn")[0]["x"] == 1
    assert s.list_campaigns()[0]["id"] == "c1"
    s.delete_campaign("c1")
    assert s.list_campaigns() == [] and s.all("c1", "squadron", M.Squadron) == []


def test_state_save_load_and_clock():
    s = Store()
    s.create_campaign("c", "n")
    st = State(meta=_meta())
    st.airbases["b"] = M.Airbase(id="b", name="B", coalition="blue", lat=25, lon=55)
    st.pilot = M.Pilot(callsign="Rook", squadron_id="s1", aircraft="F-15C")
    tgt = Target(kind="airbase", id="b", name="B", lat=25, lon=55)
    st.ato = Ato(id="ato-1", turn=1, packages=[Package(id="p1", coalition="blue", mission="CAP", target=tgt, flights=[
        Flight(id="f1", squadron_id="s1", coalition="blue", aircraft="F-15C", count=2, task="CAP")])])
    save_state(s, "c", st)
    st2 = load_state(s, "c")
    assert st2.airbases["b"].fuel.jet == 0 and st2.pilot.callsign == "Rook"
    assert st2.ato.find_flight("f1")[1].count == 2
    st2.advance_clock()
    assert st2.meta.turn == 2 and st2.meta.date.startswith("2011-06-01T12")
    assert st2.rng("a").random() == st2.rng("a").random()
    assert st2.rng("a").random() != st2.rng("b").random()


def test_geo():
    a, b = (25.0, 55.0), (26.0, 55.0)
    assert abs(geo.dist_km(a, b) - 111.2) < 1
    assert abs(geo.bearing(a, b)) < 0.01
    d = geo.destination(a, 90, 100)
    assert abs(geo.dist_km(a, d) - 100) < 0.5 and abs(geo.bearing(a, d) - 90) < 1
    assert geo.point_segment_km((25.5, 55.5), a, b) < 51 and geo.point_segment_km((25.5, 55.5), a, b) > 49
    fl = geo.front_line(a, b, 0.5, 40)
    assert abs(geo.dist_km(fl[0], fl[1]) - 40) < 0.5


def test_migrations_and_events(tmp_path):
    import sqlite3
    from sortie import db
    path = tmp_path / "m.db"
    conn = sqlite3.connect(path)          # a database created by "version 1" of the app
    conn.executescript(db.MIGRATIONS[0]); conn.execute("PRAGMA user_version = 1"); conn.commit(); conn.close()
    s = Store(path)
    assert s.schema_version == len(db.MIGRATIONS)
    evs = [{"id": "r1-1", "t": 1.0, "ev": "birth"}, {"id": "r1-2", "t": 2.0, "ev": "kill"}]
    assert s.add_events("c", 1, evs) == 2
    assert s.add_events("c", 1, evs + [{"id": "r1-3", "t": 3, "ev": "land"}]) == 1     # duplicates ignored
    assert [e["ev"] for e in s.events("c", 1)] == ["birth", "kill", "land"]
    assert s.get_cursor("w") is None
    s.set_cursor("w", "abc", 120)
    s.close()
    s2 = Store(path)                      # reopening does not re-run migrations or lose data
    assert s2.get_cursor("w") == {"file_id": "abc", "offset": 120} and len(s2.events("c", 1)) == 3


def test_json_logging(tmp_path):
    import json, logging
    from sortie import logs
    f = tmp_path / "log" / "s.jsonl"
    logs.setup("INFO", f)
    logging.getLogger("sortie.test").info("hello", extra={"turn": 3})
    for h in logging.getLogger("sortie").handlers:
        h.flush()
    rec = json.loads(f.read_text().splitlines()[-1])
    assert rec["msg"] == "hello" and rec["turn"] == 3 and rec["logger"] == "sortie.test"
    logs.setup("INFO")
