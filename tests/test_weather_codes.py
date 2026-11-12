import random
import zipfile
from datetime import datetime

import dcs
from dcs import planes

from sortie import weather
from sortie.mission import codes
from tests.test_mission import _build


def test_legacy_weather_is_upgraded():
    w = weather.normalize({"temp_c": 16, "wind_dir": 250, "wind_ms": 4, "cloud_base_m": 1800, "cloud_density": 4},
                          random.Random(1))
    assert w["state"] == "BROKEN" and w["v"] == 2 and w["preset"]
    assert w["wind_dir"] == 250 and w["home"] == "BROKEN"


def test_drift_only_steps_to_neighbours():
    rng = random.Random(3)
    w = weather.normalize({"state": "SCATTERED"}, rng)
    prev = weather.STATES.index(w["state"])
    seen = set()
    for _ in range(400):
        weather.drift(w, rng)
        now = weather.STATES.index(w["state"])
        assert abs(now - prev) <= 1
        prev = now
        seen.add(w["state"])
    assert len(seen) >= 3                      # it does move


def test_fog_only_in_the_morning():
    w = weather.normalize({"state": "OVERCAST"}, random.Random(1))
    w["fog"] = True
    assert weather.at(w, datetime(2026, 6, 1, 6, 0))["fog_m"] > 0
    assert weather.at(w, datetime(2026, 6, 1, 14, 0))["fog_m"] == 0


def test_apply_writes_wind_to_direction_and_preset():
    m = dcs.Mission()
    w = weather.normalize({"state": "OVERCAST", "wind_dir": 250, "wind_ms": 5}, random.Random(1))
    weather.apply(m, w)
    assert m.weather.wind_at_ground.direction == 70     # DCS stores the direction the wind blows TO
    assert m.weather.clouds_preset is not None


def test_laser_bombs_swapped_for_gps_under_low_cloud():
    gbu12 = planes.F_16C_50.Pylon3.GBU_12___500lb_Laser_Guided_Bomb
    pyl = [(3, {"clsid": gbu12[1]["clsid"]})]
    low = {"state": "OVERCAST", "cover": 1.0, "cloud_base_m": 900, "visibility_km": 15, "rain": 0}
    out, notes, keep, dead = weather.adapt(planes.F_16C_50, pyl, low)
    assert notes and "GPS" in keep and not dead
    assert weather.classify(weather.weapon_name(out[0][1]["clsid"])) == "GPS"
    clear = {"state": "CLEAR", "cover": 0.0, "cloud_base_m": 7600, "visibility_km": 60, "rain": 0}
    assert weather.adapt(planes.F_16C_50, pyl, clear)[1] == []


def test_weapon_classes():
    assert weather.classify("AGM-88C HARM - High Speed Anti-Radiation Missile") == "ARM"
    assert weather.classify("GBU-38 - JDAM, 500lb GBU-38") == "GPS"
    assert weather.classify("GBU-12 - 500lb Laser Guided Bomb") == "LASER"
    assert weather.classify("AGM-65D - Maverick D (IIR ASM)") == "EO"
    assert weather.classify("Mk-82 - 500lb GP Bomb LD") == "UNGUIDED"
    assert weather.below_limits({"state": "STORM"}) == "storms"


def test_codes_briefing_and_datalinks(theaters, tmp_path):
    st, ato, res, _ = _build(theaters, "gulf_crisis", tmp_path)
    f = res.briefing["flight"]
    assert len(f["mode3"]) == 4 and set(f["mode3"]) <= set("01234567")
    assert f["laser"] in codes.LASER_CODES and f["bingo"] and f["joker"]
    m3 = [codes.mode3(ato, fl) for p in ato.packages for fl in p.flights]
    assert len(m3) == len(set(m3))             # unique per flight
    with zipfile.ZipFile(res.path) as z:
        mission = z.read("mission").decode()
    if any(fl.aircraft in codes._LINKS for fid in res.selection["flights"] for fl in [ato.find_flight(fid)[1]]):
        assert '["datalinks"]' in mission and res.briefing["stn"]
    assert "Preset" in mission or res.briefing["weather"].get("state") == "CLEAR"


def test_ww2_has_no_codes(theaters, tmp_path):
    _, _, res, _ = _build(theaters, "forager_1944", tmp_path)
    assert res.briefing["flight"]["mode3"] == "" and res.briefing["flight"]["laser"] == ""
