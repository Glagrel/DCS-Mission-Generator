"""Campaign weather: a believable picture that changes gradually from cycle to cycle, written into
DCS with real cloud presets, and what it means for the weapons a flight can use.

The weather lives in ``st.meta.weather`` as a plain dict (old campaigns and theater templates that
only have ``cloud_density`` / ``cloud_base_m`` etc. are upgraded by ``normalize``).

States, ordered from best to worst: CLEAR, SCATTERED, BROKEN, OVERCAST, RAIN, STORM. Each cycle the
state either stays or moves to a NEIGHBOUR (never clear to storm in one step), with a Metropolis
acceptance that keeps the long-run mix near the theater's typical weather. Fog forms only in the
early morning and burns off by mid-morning.

Weapon limits (idea and thresholds adapted from SQE, github.com/MarkuzJuniuz/SQE, MIT): laser
weapons need a cloud-free line of sight (ceiling 10,000 ft or a sky with gaps, 8 km visibility, no
rain); imaging/TV weapons a 3,000 ft ceiling and 6 km; unguided weapons 1,500 ft and 5 km. GPS
weapons, anti-radiation missiles and air-to-air weapons ignore the weather. ``adapt`` swaps a ruled-
out weapon for the closest-weight GPS bomb the same pylon can carry.

Wind direction is stored as the direction the wind blows FROM (as ATC reads it); DCS stores the
direction it blows TO, which ``apply`` converts.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

STATES = ["CLEAR", "SCATTERED", "BROKEN", "OVERCAST", "RAIN", "STORM"]
LABEL = {"CLEAR": "clear", "SCATTERED": "scattered cloud", "BROKEN": "broken cloud", "OVERCAST": "overcast",
         "RAIN": "rain", "STORM": "heavy rain and storms"}
FT = 0.3048

# per state: (cover lo, hi), (cloud base m MSL lo, hi), (visibility km lo, hi), wind factor, turbulence (DCS units),
# QNH offset mmHg, temperature offset C
_P = {
    "CLEAR":     ((0.00, 0.10), (7600, 7600), (35, 70), 0.8, 0, +3, +1.5),
    "SCATTERED": ((0.20, 0.40), (1400, 2700), (25, 50), 0.9, 2, +2, +0.5),
    "BROKEN":    ((0.60, 0.85), (800, 2100), (15, 35), 1.0, 4, 0, 0.0),
    "OVERCAST":  ((1.00, 1.00), (450, 1400), (8, 20), 1.2, 6, -2, -0.5),
    "RAIN":      ((1.00, 1.00), (450, 900), (4, 10), 1.5, 10, -6, -1.5),
    "STORM":     ((1.00, 1.00), (450, 700), (2, 6), 2.4, 22, -12, -3.0),
}
# dcs.cloud_presets.Clouds member names that suit each state
_PRESETS = {
    "SCATTERED": ["LightScattered1", "LightScattered2", "HighScattered1", "HighScattered2", "HighScattered3",
                  "Scattered1", "Scattered2"],
    "BROKEN": ["Scattered3", "Scattered4", "Scattered5", "Scattered6", "Scattered7", "Broken1", "Broken2", "Broken3",
               "Broken4"],
    "OVERCAST": ["Broken5", "Broken6", "Broken7", "Broken8", "Overcast1", "Overcast2", "Overcast3", "Overcast4",
                 "Overcast5", "Overcast6", "Overcast7"],
    "RAIN": ["OvercastAndRain1", "OvercastAndRain2", "OvercastAndRain3"],
    "STORM": ["OvercastAndRain1", "OvercastAndRain2", "OvercastAndRain3"],
}
STAY = 0.6            # chance a 6-hour cycle simply keeps the state
FOG_CHANCE = 0.12     # chance that a non-clear, non-storm cycle brings dawn fog


def _u(rng, lo: float, hi: float) -> float:
    return lo + (hi - lo) * rng.random()


def state_from_legacy(w: Dict[str, Any]) -> str:
    """Map the old density-based weather (0-10) onto a state."""
    d = int(w.get("cloud_density", 0) or 0)
    if w.get("precipitation"):
        return "RAIN"
    return "CLEAR" if d <= 1 else "SCATTERED" if d <= 3 else "BROKEN" if d <= 6 else "OVERCAST" if d <= 8 else "RAIN"


def _climate(w: Dict[str, Any]) -> List[float]:
    """Long-run weights of the states: peaked at the theater's typical state (`home`), halving per step."""
    home = STATES.index(w.get("home", "SCATTERED"))
    pi = [0.5 ** abs(i - home) for i in range(len(STATES))]
    pi[-1] *= 0.5                                      # storms are rarer than the walk alone would make them
    s = sum(pi)
    return [p / s for p in pi]


def _draw(state: str, rng, w: Dict[str, Any], blend: float = 1.0) -> None:
    """Pick the in-state parameters (cover, base, visibility, wind, ...), moving `blend` of the way from the
    current values so a cycle that keeps its state changes only a little."""
    (c0, c1), (b0, b1), (v0, v1), wf, turb, dq, dt = _P[state]
    base_wind = float(w.get("wind_ms_home", w.get("wind_ms", 4)) or 4)

    def mix(key: str, new: float) -> float:
        old = w.get(key)
        return new if old is None or blend >= 1.0 else float(old) + (new - float(old)) * blend

    w["cover"] = round(min(max(mix("cover", _u(rng, c0, c1)), c0), c1), 2)
    w["cloud_base_m"] = int(min(max(mix("cloud_base_m", _u(rng, b0, b1)), b0), b1))
    w["visibility_km"] = round(min(max(mix("visibility_km", _u(rng, v0, v1)), v0), v1), 1)
    w["wind_ms"] = round(max(0.0, mix("wind_ms", base_wind * wf * _u(rng, 0.8, 1.25))), 1)
    w["turbulence"] = turb
    w["qnh_mmhg"] = round(761 + dq + _u(rng, -2, 2), 1)
    w["temp_c"] = round(float(w.get("temp_home", w.get("temp_c", 15))) + dt + _u(rng, -2, 2), 1)
    w["rain"] = 2 if state == "STORM" else 1 if state == "RAIN" else 0
    w["fog"] = state not in ("CLEAR", "STORM") and rng.random() < FOG_CHANCE
    w["preset"] = _preset(state, w["cloud_base_m"], rng)
    if w["preset"]:
        from dcs.cloud_presets import Clouds
        pv = Clouds[w["preset"]].value
        w["cloud_base_m"] = int(min(max(w["cloud_base_m"], pv.min_base), pv.max_base))
    # legacy fields still read elsewhere (GUI)
    w["cloud_density"] = {"CLEAR": 0, "SCATTERED": 3, "BROKEN": 6, "OVERCAST": 8, "RAIN": 9, "STORM": 10}[state]


def _preset(state: str, base_m: float, rng) -> str:
    pool = _PRESETS.get(state)
    if not pool:
        return ""
    try:
        from dcs.cloud_presets import Clouds
        ok = [n for n in pool if Clouds[n].value.min_base <= base_m <= Clouds[n].value.max_base]
    except Exception:                                   # pydcs without presets: plain clouds
        return ""
    return rng.choice(ok or pool)


def normalize(w: Optional[Dict[str, Any]], rng) -> Dict[str, Any]:
    """Fill in a full weather dict (in place when given one). Idempotent for a complete dict."""
    w = w if w is not None else {}
    if w.get("state") in STATES and w.get("v") == 2:
        return w
    state = w.get("state") if w.get("state") in STATES else state_from_legacy(w)
    w.setdefault("home", state)
    w.setdefault("wind_ms_home", float(w.get("wind_ms", 4) or 4))
    w.setdefault("temp_home", float(w.get("temp_c", 15) or 15))
    w["wind_dir"] = int(w.get("wind_dir", 270)) % 360
    w["state"] = state
    _draw(state, rng, w, blend=1.0)
    w["v"] = 2
    return w


def drift(w: Dict[str, Any], rng) -> Dict[str, Any]:
    """Advance the weather one cycle: stay, or step to a neighbouring state."""
    normalize(w, rng)
    pi = _climate(w)
    s = STATES.index(w["state"])
    if rng.random() >= STAY:
        nb = s - 1 if rng.random() < 0.5 else s + 1
        if 0 <= nb < len(STATES) and rng.random() < min(1.0, pi[nb] / max(pi[s], 1e-9)):
            s = nb
    changed = STATES[s] != w["state"]
    w["state"] = STATES[s]
    w["wind_dir"] = int((w.get("wind_dir", 270) + rng.randint(-30, 30)) % 360)
    _draw(w["state"], rng, w, blend=1.0 if changed else 0.4)
    return w


def at(w: Dict[str, Any], when: Optional[datetime]) -> Dict[str, Any]:
    """The weather as it is at a given local time: dawn fog thickens visibility before 09:30."""
    out = dict(w or {})
    out["fog_m"] = 0
    if out.get("fog") and when is not None:
        hour = when.hour + when.minute / 60.0
        if 4.0 <= hour < 9.5:
            out["fog_m"] = int(500 + 3500 * min(1.0, max(0.0, (hour - 5.0) / 4.5)))
            out["visibility_km"] = round(min(float(out.get("visibility_km", 80)), out["fog_m"] / 1000.0), 1)
    return out


def ceiling_m(w: Dict[str, Any]) -> float:
    """Lowest broken/overcast layer (m); 'unlimited' when the sky has gaps."""
    return float(w.get("cloud_base_m", 7600)) if float(w.get("cover", 0)) >= 0.5 else 99999.0


def metar(w: Dict[str, Any]) -> str:
    """Compact kneeboard form, e.g. 'OVC020 7KM RA 240/12KT Q1013'."""
    if not w:
        return ""
    c = float(w.get("cover", 0))
    sky = "SKC" if c < 0.1 else "FEW" if c < 0.3 else "SCT" if c < 0.55 else "BKN" if c < 0.9 else "OVC"
    out = [sky if sky == "SKC" else f"{sky}{int(round(w.get('cloud_base_m', 0) / FT / 100.0)):03d}",
           f"{float(w.get('visibility_km', 80)):.0f}KM"]
    if w.get("rain"):
        out.append("+TSRA" if w["rain"] == 2 else "RA")
    if w.get("fog_m"):
        out.append("FG")
    out.append(f"{int(w.get('wind_dir', 0)) % 360:03d}/{float(w.get('wind_ms', 0)) * 1.94384:02.0f}KT")
    if w.get("qnh_mmhg"):
        out.append(f"Q{w['qnh_mmhg'] * 1.33322:.0f}")
    return " ".join(out)


def describe(w: Dict[str, Any], units: str = "imperial") -> str:
    from . import measure
    if not w:
        return ""
    st = w.get("state", "CLEAR")
    if st == "CLEAR" or float(w.get("cover", 0)) < 0.2:
        sky = "clear skies" if st == "CLEAR" else "few clouds"
    else:
        sky = f"{LABEL[st]}, base {measure.alt(w.get('cloud_base_m', 0), units)}"
    vis = float(w.get("visibility_km", 80))
    bits = [sky, f"visibility {vis:.0f} km" if vis >= 10 else f"visibility {vis:.1f} km"]
    if w.get("fog_m"):
        bits.append("morning fog")
    bits.append("wind " + measure.wind(w.get("wind_dir", 0), w.get("wind_ms", 0), units))
    bits.append(measure.temp(w.get("temp_c", 15), units))
    if w.get("qnh_mmhg"):
        bits.append(f"QNH {w['qnh_mmhg'] * 1.33322:.0f} hPa / {w['qnh_mmhg'] / 25.4:.2f} inHg")
    return ", ".join(bits)


def apply(m, w: Dict[str, Any]) -> None:
    """Write the weather into a pydcs mission."""
    if not w:
        return
    from dcs.weather import Wind
    wx = m.weather
    wx.atmosphere_type = 0
    wx.season_temperature = float(w.get("temp_c", 15))
    if w.get("qnh_mmhg"):
        wx.qnh = float(w["qnh_mmhg"])
    wx.visibility_distance = int(min(max(float(w.get("visibility_km", 80)), 0.5), 80.0) * 1000)
    if w.get("preset"):
        from dcs.cloud_presets import Clouds
        wx.clouds_preset = Clouds[w["preset"]].value
        wx.clouds_base = int(w.get("cloud_base_m", 2000))
        wx.clouds_density = 0
        wx.clouds_iprecptns = 0
    else:
        wx.clouds_preset = None
        wx.clouds_base = int(w.get("cloud_base_m", 2000))
        wx.clouds_density = int(w.get("cloud_density", 0))
        wx.clouds_thickness = int(w.get("cloud_thickness_m", 200))
    wx.enable_fog = bool(w.get("fog_m"))
    if w.get("fog_m"):
        wx.fog_visibility = int(w["fog_m"])
        wx.fog_thickness = 200
    frm, ms = int(w.get("wind_dir", 0)), float(w.get("wind_ms", 0))
    to = lambda deg: int(round((deg + 180) % 360))        # DCS stores the direction the wind blows TO
    wx.wind_at_ground = Wind(to(frm), round(ms, 1))
    wx.wind_at_2000 = Wind(to(frm + 20), round(ms * 1.7, 1))
    wx.wind_at_8000 = Wind(to(frm + 45), round(ms * 3.0, 1))
    wx.turbulence_at_ground = float(w.get("turbulence", 0))


# -- weapons ---------------------------------------------------------------------------------------------
LASER_CEIL_M, LASER_VIS_KM = 10000 * FT, 8.0
EO_CEIL_M, EO_VIS_KM = 3000 * FT, 6.0
VISUAL_CEIL_M, VISUAL_VIS_KM = 1500 * FT, 5.0


def classify(name: str) -> str:
    n = (name or "").lower()
    if "anti-radiation" in n or "harm" in n or "agm-88" in n or "agm-45" in n or "alarm" in n or "shrike" in n:
        return "ARM"
    if any(k in n for k in ("jdam", "gps", "jsow", "agm-154", "slam", "gbu-54", "gbu-38", "gbu-31", "gbu-32",
                            "jassm", "agm-158", "tomahawk", "harpoon", "exocet", "kh-")):
        return "GPS"
    if "laser" in n or re.search(r"gbu-(10|12|16|24|27|28)\b", n) or "paveway" in n or "agm-65e" in n \
            or "agm-65l" in n or "kab-" in n:
        return "LASER"
    if any(k in n for k in ("maverick", "iir", " tv ", "walleye", "agm-62", "agm-65", "optical")):
        return "EO"
    if re.search(r"\baim-|\baam\b|\br-(27|24|77|73|60|3s|33|40)|sidewinder|sparrow|amraam|phoenix", n):
        return "A2A"
    if any(k in n for k in ("mk-8", "mk 8", "mk_8", "cbu", "rocket", "hydra", "m117", "m-117", "fab-", "ofab", "s-8",
                            "s-5", "s-24", "lau-68", "lau-61", "bomb", "rb-")):
        return "UNGUIDED"
    return "OTHER"


def usable(cls: str, w: Dict[str, Any]) -> bool:
    if cls in ("GPS", "ARM", "A2A", "OTHER") or not w:
        return True
    ceil, vis, rain = ceiling_m(w), float(w.get("visibility_km", 80)), int(w.get("rain", 0))
    if cls == "LASER":
        return ceil >= LASER_CEIL_M and vis >= LASER_VIS_KM and rain == 0
    if cls == "EO":
        return ceil >= EO_CEIL_M and vis >= EO_VIS_KM and rain < 2
    if cls == "UNGUIDED":
        return ceil >= VISUAL_CEIL_M and vis >= VISUAL_VIS_KM
    return True


def _wdata(clsid: str) -> Dict[str, Any]:
    from dcs.weapons_data import weapon_ids
    d = weapon_ids.get(clsid)
    return d if isinstance(d, dict) else {}


def weapon_name(clsid: str) -> str:
    return str(_wdata(clsid).get("name", ""))


def _short(name: str) -> str:
    return re.sub(r"\s+", " ", re.split(r"\s[-:]\s", name)[0]).strip()[:40] or name[:40]


def adapt(actype, pylons: List[Tuple[int, Dict[str, Any]]], w: Dict[str, Any]) \
        -> Tuple[List[Tuple[int, Dict[str, Any]]], List[str], set, set]:
    """Swap every weapon the weather rules out for the closest-weight GPS bomb on the same pylon.
    Returns (new pylons, notes, usable A/G classes, A/G classes left unusable)."""
    out, notes, keep, dead = [], [], set(), set()
    for n, item in pylons:
        clsid = item.get("clsid") or item.get("CLSID") or ""
        nm = weapon_name(clsid)
        cls = classify(nm)
        if cls in ("A2A", "OTHER") or usable(cls, w):
            if cls not in ("A2A", "OTHER"):
                keep.add(cls)
            out.append((n, item))
            continue
        best, gap = None, None
        P = getattr(actype, f"Pylon{n}", None)
        if P is not None:
            for attr, val in vars(P).items():
                if attr.startswith("_") or not isinstance(val, tuple) or len(val) < 2 or not isinstance(val[1], dict):
                    continue
                c2 = val[1].get("clsid", "")
                n2 = weapon_name(c2).lower()
                if classify(n2) != "GPS" or "agm" in n2 or "slam" in n2 or not re.search(r"jdam|gbu-", n2):
                    continue                              # a GPS bomb for a bomb/Maverick pylon, never a cruise missile
                g = abs(float(_wdata(c2).get("weight", 0) or 0) - float(_wdata(clsid).get("weight", 0) or 0))
                if gap is None or g < gap:
                    best, gap = c2, g
        if best:
            new = copy.deepcopy(item)
            new.pop("CLSID", None)
            new["clsid"] = best
            new.pop("settings", None)
            out.append((n, new))
            notes.append(f"{_short(nm)} -> {_short(weapon_name(best))}")
            keep.add("GPS")
        else:
            out.append((n, item))
            dead.add(cls)
    return out, list(dict.fromkeys(notes)), keep, dead


NEEDS = {"STRIKE": {"GPS", "LASER", "UNGUIDED", "EO"}, "CAS": {"GPS", "LASER", "UNGUIDED", "EO"},
         "INTERDICTION": {"GPS", "LASER", "UNGUIDED", "EO"}, "DEAD": {"GPS", "LASER", "UNGUIDED", "EO", "ARM"},
         "SEAD": {"ARM", "GPS"}, "ANTISHIP": {"GPS", "LASER", "UNGUIDED", "EO"}}


def below_limits(w: Dict[str, Any]) -> str:
    """A reason when no attack sortie should launch at all (storm, fog, ceiling and visibility), else ''."""
    if not w:
        return ""
    if w.get("state") == "STORM":
        return "storms"
    if w.get("fog_m") and float(w.get("visibility_km", 80)) < 1.5:
        return "fog"
    if ceiling_m(w) < 180 or float(w.get("visibility_km", 80)) < 1.5:
        return "ceiling and visibility below limits"
    return ""
