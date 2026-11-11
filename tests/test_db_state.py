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
