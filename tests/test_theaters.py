import copy

import pytest

from sortie import config, terrain, theater, units
from sortie.campaign import CampaignError, CareerOptions, build_state, create_campaign, playable_squadrons
from sortie.state import load_state
from tests.conftest import make_state

IDS = ["coldwar_1985", "forager_1944", "gulf_crisis"]


def test_three_templates_present(theaters):
    assert set(IDS) <= set(theaters)


@pytest.mark.parametrize("tid", IDS)
def test_template_valid(theaters, tid):
    assert theater.validate(theaters[tid]) == []


@pytest.mark.parametrize("tid", IDS)
def test_template_content(theaters, tid):
    t = theaters[tid]
    for side in ("blue", "red"):
        assert [s for s in t.squadrons if s.coalition == side]
        assert [a for a in t.airbases + t.carriers if a.coalition == side]
        assert [n for n in t.supply_nodes if n.coalition == side and n.output > 0]
        assert [g for g in t.ground_units if g.coalition == side]
    assert t.fronts and t.supply_routes and t.sam_sites
    assert t.start.date and t.start.weather
    assert playable_squadrons(t, "blue", units.flyable_modules())


def test_ww2_has_no_modern_capabilities(theaters):
    t = theaters["forager_1944"]
    for co in t.coalitions.values():
        assert not {"AWACS", "TANKER", "RADAR_SAM", "PGM", "HELO"} & set(co.capabilities)
    assert all(units.year_of(s.aircraft) <= 1945 for s in t.squadrons)
    assert all(units.sam_template(s.template)["role"] in ("aaa", "ewr") for s in t.sam_sites)


def test_coldwar_units_are_period(theaters):
    t = theaters["coldwar_1985"]
    assert all(1945 < units.year_of(s.aircraft) <= 1985 for s in t.squadrons)
    assert "AWACS" not in t.coalitions["red"].capabilities


def test_era_filter():
    assert units.in_era("F-15C", 1985, "coldwar") and not units.in_era("F-16C_50", 1985, "coldwar")
    assert not units.in_era("P-51D", 1985, "coldwar") and units.in_era("P-51D", 1944, "ww2")
    assert not units.in_era("F-15C", 1944, "ww2")
    assert "F4U-1D" in units.flyable_in_era(1944, "ww2") and "A-10C_2" not in units.flyable_in_era(1985, "coldwar")
    assert not units.in_era("NoSuchType", 1990, "coldwar")       # unknown -> year 2000


def test_validation_catches_errors(theaters):
    t = copy.deepcopy(theaters["forager_1944"])
    t.squadrons[0].aircraft = "F-15C"
    t.airbases[0].dcs_name = "Nowhere"
    t.sam_sites[0].template = "SA-10"
    t.coalitions["blue"].countries = ["USA"]
    t.ground_units[0].country = "Japan"
    errs = "\n".join(theater.validate(t))
    assert "F-15C" in errs and "Nowhere" in errs and "SA-10" in errs and "not in coalition" in errs


def test_terrain_abstraction():
    assert terrain.is_supported("GermanyCW") and terrain.is_supported("PersianGulf")
    assert terrain.resolve("MarianaIslandsWWII") == ("MarianaIslands", True)   # documented fallback
    assert not terrain.is_supported("Atlantis")
    lat, lon = terrain.airport_latlon("PersianGulf", "Al Dhafra AFB")
    assert abs(lat - 24.25) < 0.1 and abs(lon - 54.55) < 0.1


def test_capable_missions():
    assert "CAP" in units.capable_missions("F-15C") and "STRIKE" not in units.capable_missions("F-15C")
    assert units.capable_missions("E-3A") == ["AWACS"]
    assert units.air_rating("F-15C") > units.air_rating("MiG-21Bis") > units.air_rating("A-10A")


def test_build_state_and_ownership(theaters):
    st = make_state(theaters, "gulf_crisis")
    assert st.pilot.squadron_id == "77fs" and st.pilot.aircraft == "F-16C_50" and st.pilot.rank
    assert st.squadrons["77fs"].is_player and st.airbases["cvn73"].kind == "carrier"
    assert st.naval_groups["cvn73"].role == "carrier" and st.airbases["dhafra"].fuel.jet == 1500
    assert st.sam_sites["sa10_ba"].range_km == 75
    blue = [g for g in st.ground_units.values() if g.coalition == "blue"][0]
    assert blue.lat != 0 and blue.lon != 0
    # not owned -> rejected
    s = config.Settings(owned_modules=["A-10C_2"])
    with pytest.raises(CampaignError):
        make_state(theaters, "gulf_crisis", settings=s)
    assert make_state(theaters, "gulf_crisis", squadron="74fs", settings=s).pilot.aircraft == "A-10C_2"
    # AI-only airframe or wrong side -> rejected
    for sq in ("968eaacs", "tfb9a"):
        with pytest.raises(CampaignError):
            make_state(theaters, "gulf_crisis", squadron=sq)


def test_ww2_fuel_is_avgas(theaters):
    st = make_state(theaters, "forager_1944")
    assert st.airbases["isley"].fuel.avgas == 500 and st.airbases["isley"].fuel.jet == 0
    assert st.pilot.rank == "Ensign"


def test_create_campaign_persists(theaters, store):
    opt = CareerOptions(theater_id="coldwar_1985", squadron_id="53tfs", callsign="Duke")
    cid = create_campaign(store, theaters["coldwar_1985"], opt)
    st = load_state(store, cid)
    assert st.meta.turn == 1 and st.meta.date == "1985-06-10T05:30:00"
    assert len(st.squadrons) == len(theaters["coldwar_1985"].squadrons)
    assert store.history(cid, "campaign")
