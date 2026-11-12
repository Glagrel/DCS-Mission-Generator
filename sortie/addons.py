"""Optional community mission scripts SORTIE can embed, each switched on in Settings:

  splash  Splash Damage (stephenpostlethwaite)  - bigger blasts, cook-offs, cluster spread
  skynet  Skynet IADS (walder) + MIST           - the enemy air defence works as a network
  hound   Hound ELINT (uriba107)                - your ELINT aircraft locate enemy radars
  growler Growler AEA (Timberwolf, DCS forum)   - EA-18G jamming for human Growler crews

The script files live in vendor/addons/ (tools/fetch_addons.py downloads the GitHub ones).
Their settings are edited in the GUI:
  * Splash Damage: every option of the script's own `splash_damage_options` table, read
    straight out of the vendored file (so the list follows the script version). Changed
    values are written into the embedded copy right after that table, before the script
    reads any of them.
  * Skynet, Hound and Growler: SORTIE builds the set-up (which sites, radars and platforms)
    from the campaign, with the knobs listed in SCHEMAS below.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths

VENDOR = paths.PROJECT_ROOT / "vendor" / "addons"

INFO: Dict[str, Dict[str, Any]] = {
    "splash": {"name": "Splash Damage", "files": ["Splash_Damage.lua"],
               "source": "github.com/stephenpostlethwaite/DCSSplashDamageScript",
               "about": "Realistic blast radius, secondary explosions, vehicle cook-offs and cluster bomb "
                        "spread. Affects every weapon in the mission (yours and the AI's)."},
    "skynet": {"name": "Skynet IADS", "files": ["mist.lua", "skynet-iads-compiled.lua"],
               "source": "github.com/walder/Skynet-IADS",
               "about": "Turns the enemy's SAM sites and early-warning radars into one network: sites stay "
                        "dark until the EWRs cue them, go live at the last moment and shut down against HARMs. "
                        "AI EA-18G/EA-6B flights jam through Skynet's own jammer."},
    "hound": {"name": "Hound ELINT", "files": ["HoundElint.lua"],
              "source": "github.com/uriba107/dcs-hound",
              "about": "Your AWACS, Hawkeyes, Vikings, Hercules and other ELINT-capable aircraft triangulate "
                       "enemy radars and mark them on the F10 map, with an F10 radio menu for SAM reports."},
    "growler": {"name": "Growler AEA (EA-18G jamming)", "files": ["Growler_AEA.lua"],
                "source": "forum.dcs.world/topic/385186 (download 'Growler AEA Script.lua' and save it as "
                          "vendor/addons/Growler_AEA.lua)",
                "about": "Stand-off and escort jamming for HUMAN EA-18G crews (CJS Super Hornet mod), "
                         "controlled from its own F10 AEA menu. AI Growlers jam through Skynet instead."},
}

# Knobs SORTIE exposes for the scripts it sets up itself. type: bool | int | float | choice | str
SCHEMAS: Dict[str, List[Dict[str, Any]]] = {
    "skynet": [
        {"key": "sides", "type": "choice", "default": "enemy", "choices": ["enemy", "both"], "section": "Network",
         "label": "Which air defences Skynet runs", "help": "enemy = only the side you fight; both = yours as well"},
        {"key": "go_live_pct", "type": "int", "default": 100, "min": 50, "max": 150, "section": "Network",
         "label": "Go-live range, % of the missile's kill range",
         "help": "Lower = sites wait longer before radiating (deadlier, harder to find)"},
        {"key": "engagement_zone", "type": "choice", "default": "kill", "choices": ["kill", "search"],
         "section": "Network", "label": "Sites go live when the target is in their", "help": ""},
        {"key": "harm_detection", "type": "int", "default": -1, "min": -1, "max": 100, "section": "Network",
         "label": "HARM detection chance % (-1 = Skynet's per-type default)", "help": ""},
        {"key": "awacs_as_ew", "type": "bool", "default": True, "section": "Network",
         "label": "Their AWACS act as early-warning radars", "help": ""},
        {"key": "point_defence", "type": "bool", "default": True, "section": "Network",
         "label": "SA-15/SA-19/Tor-class sites near a long-range site defend it against HARMs", "help": ""},
        {"key": "update_interval", "type": "int", "default": 5, "min": 2, "max": 30, "section": "Network",
         "label": "Network update interval (s)", "help": ""},
        {"key": "ai_jammers", "type": "bool", "default": True, "section": "Jamming",
         "label": "AI EA-18G / EA-6B flights jam enemy radars (Skynet jammer)", "help": ""},
        {"key": "jammer_range_nm", "type": "int", "default": 160, "min": 20, "max": 300, "section": "Jamming",
         "label": "AI jammer maximum effective range (nm)", "help": ""},
        {"key": "radio_menu", "type": "bool", "default": False, "section": "Debug",
         "label": "Skynet F10 radio menu (status / debug toggles)", "help": ""},
        {"key": "debug_status", "type": "bool", "default": False, "section": "Debug",
         "label": "Show network status on screen", "help": ""},
    ],
    "hound": [
        {"key": "markers", "type": "bool", "default": True, "section": "Map", "label": "Mark located radars on the F10 map",
         "help": ""},
        {"key": "marker_type", "type": "choice", "default": "CIRCLE",
         "choices": ["NONE", "SITE_ONLY", "POINT", "CIRCLE", "DIAMOND", "OCTAGON", "POLYGON"], "section": "Map",
         "label": "Marker style (uncertainty area)", "help": ""},
        {"key": "site_markers", "type": "bool", "default": True, "section": "Map", "label": "Mark whole sites", "help": ""},
        {"key": "prebriefed", "type": "bool", "default": True, "section": "Intel",
         "label": "Sites the campaign already knows start as pre-briefed contacts", "help": ""},
        {"key": "bda", "type": "bool", "default": True, "section": "Intel", "label": "Report destroyed radars (BDA)",
         "help": ""},
        {"key": "text", "type": "bool", "default": True, "section": "Reports",
         "label": "Text reports and F10 SAM controller menu", "help": ""},
        {"key": "alert_on_launch", "type": "bool", "default": False, "section": "Reports",
         "label": "Alert on SAM launch", "help": ""},
        {"key": "nato_names", "type": "bool", "default": True, "section": "Reports",
         "label": "NATO reporting names (brevity)", "help": ""},
        {"key": "pos_errors", "type": "bool", "default": False, "section": "Platforms",
         "label": "Model platform navigation errors (less precise)", "help": ""},
        {"key": "scan_interval", "type": "int", "default": 5, "min": 2, "max": 30, "section": "Platforms",
         "label": "Scan interval (s)", "help": ""},
    ],
    "growler": [
        {"key": "jammer_types", "type": "str", "default": "EA-18G", "section": "Jammers",
         "label": "Human aircraft types that get the AEA menu (comma separated)",
         "help": "The script works on units whose name starts with [EA-18G]; SORTIE names those seats for you"},
        {"key": "start_delay_s", "type": "int", "default": 5, "min": 1, "max": 60, "section": "Jammers",
         "label": "Load the script this many seconds after mission start (the author asks for a delay)",
         "help": ""},
    ],
}
GROWLER_PREFIX = "[EA-18G]"


# -- Splash Damage option table ------------------------------------------------------------------
_OPT = re.compile(r'^\s*\["(?P<k>\w+)"\]\s*=\s*(?P<v>.+?)\s*,\s*(?:--\s*(?P<c>.*))?$')
_SECTION = re.compile(r"^\s*-{8,}\s*(?P<s>[^-].*?)\s*-{3,}\s*$")


def _parse_value(raw: str):
    raw = raw.strip()
    if raw in ("true", "false"):
        return "bool", raw == "true"
    if re.fullmatch(r"-?\d+", raw):
        return "number", int(raw)
    if re.fullmatch(r"-?\d*\.\d+(e-?\d+)?|-?\d+e-?\d+", raw):
        return "number", float(raw)
    m = re.fullmatch(r'"(.*)"', raw)
    if m:
        return "str", m.group(1)
    return None, None                    # tables and expressions are left as the script has them


def _table_span(lines: List[str], name: str):
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^\s*{name}\s*=\s*\{{", ln)), None)
    if start is None:
        return None, None
    depth = 0
    for i in range(start, len(lines)):
        code = lines[i].split("--", 1)[0]
        depth += code.count("{") - code.count("}")
        if depth <= 0 and i > start:
            return start, i
    return start, None


def splash_schema(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every editable option of splash_damage_options in the vendored script, in file order."""
    path = path or VENDOR / "Splash_Damage.lua"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    a, b = _table_span(lines, "splash_damage_options")
    if a is None or b is None:
        return []
    out, section = [], "General"
    for ln in lines[a + 1:b]:
        s = _SECTION.match(ln)
        if s:
            section = s.group("s").strip()
            continue
        m = _OPT.match(ln)
        if not m:
            continue
        typ, val = _parse_value(m.group("v"))
        if typ is None:
            continue
        out.append({"key": m.group("k"), "type": typ, "default": val, "section": section,
                    "label": m.group("k").replace("_", " "), "help": (m.group("c") or "").strip()})
    return out


def schema(key: str) -> List[Dict[str, Any]]:
    return splash_schema() if key == "splash" else SCHEMAS.get(key, [])


def _coerce(field: Dict[str, Any], v):
    t = field["type"]
    try:
        if t == "bool":
            return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
        if t == "int":
            v = int(float(v))
        elif t in ("float", "number"):
            v = float(v)
            v = int(v) if t == "number" and v.is_integer() else v
        elif t == "choice":
            return v if v in field["choices"] else field["default"]
        else:
            return str(v)
    except (TypeError, ValueError):
        return field["default"]
    lo, hi = field.get("min"), field.get("max")
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def params(settings, key: str) -> Dict[str, Any]:
    """Full parameter set for an add-on: defaults with the user's changes applied."""
    saved = ((settings.addons or {}).get(key) or {}).get("params") or {}
    out = {}
    for f in schema(key):
        out[f["key"]] = _coerce(f, saved[f["key"]]) if f["key"] in saved else f["default"]
    return out


def changed_params(settings, key: str) -> Dict[str, Any]:
    """Only the values that differ from the script's defaults."""
    defaults = {f["key"]: f["default"] for f in schema(key)}
    return {k: v for k, v in params(settings, key).items() if defaults.get(k) != v}


def clean_params(key: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a parameter patch from the GUI against the schema; unknown keys are dropped."""
    fields = {f["key"]: f for f in schema(key)}
    return {k: _coerce(fields[k], v) for k, v in (data or {}).items() if k in fields}


# -- availability ------------------------------------------------------------------------------------
# Add-ons on the back burner: hidden from Settings and never loaded, code kept for later.
# growler: the Growler AEA script cannot be downloaded at the moment (forum attachment).
SHELVED = {"growler"}


def available(key: str) -> bool:
    return all((VENDOR / f).is_file() for f in INFO[key]["files"])


def is_on(settings, key: str) -> bool:
    return key not in SHELVED and bool(((settings.addons or {}).get(key) or {}).get("enabled")) and available(key)


def status(settings) -> List[Dict[str, Any]]:
    out = []
    for key, info in INFO.items():
        if key in SHELVED:
            continue
        fields = schema(key)
        values = params(settings, key)
        out.append({"key": key, "name": info["name"], "about": info["about"], "source": info["source"],
                    "available": available(key),
                    "missing": [f for f in info["files"] if not (VENDOR / f).is_file()],
                    "enabled": bool(((settings.addons or {}).get(key) or {}).get("enabled")),
                    "fields": [{**f, "value": values.get(f["key"])} for f in fields],
                    "changed": len(changed_params(settings, key))})
    return out


# -- embedding -------------------------------------------------------------------------------------
def patched_splash(settings, dest_dir: Path) -> Path:
    """Copy of the Splash Damage script with the user's option changes inserted right after the
    option table, so they are in place before the script builds its menus and handlers."""
    src = VENDOR / "Splash_Damage.lua"
    lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
    _, end = _table_span(lines, "splash_damage_options")
    changes = changed_params(settings, "splash")
    if end is not None and changes:
        from .mission.scripts import to_lua
        inject = ["-- SORTIE: options changed in the SORTIE settings"] + \
                 [f'splash_damage_options["{k}"] = {to_lua(v)}' for k, v in changes.items()]
        lines = lines[:end + 1] + inject + lines[end + 1:]
    out = dest_dir / "Splash_Damage.lua"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


SHORAD = ("SA-15", "SA-19", "SA-8", "HQ-7", "ROLAND", "RAPIER", "AVENGER", "CHAPARRAL", "SA-9", "SA-13")
JAMMER_TYPES = ("EA-18G", "EA-6B")


def lua_config(settings, st, man: Dict[str, Any], m=None) -> Dict[str, Any]:
    """What sortie_addons.lua needs at run time, built from the mission manifest (and the pydcs
    mission `m`, for the real unit names)."""
    from . import geo

    def unit_names(group: str, n: int) -> List[str]:
        g = m.find_group(group) if m is not None else None
        return [str(u.name) for u in g.units] if g is not None else [f"{group}-{i + 1}" for i in range(n)]

    cfg: Dict[str, Any] = {}
    player = st.meta.player_side
    enemy = "red" if player == "blue" else "blue"
    if is_on(settings, "skynet"):
        p = params(settings, "skynet")
        sides = [enemy] if p["sides"] == "enemy" else ["red", "blue"]
        nets = []
        for side in sides:
            sites, ewr, pd_pairs, awacs, jammers = [], [], [], [], []
            groups = [(n, v) for n, v in man.items() if v.get("kind") == "sam_site"
                      and st.sam_sites.get(v.get("id")) is not None and st.sam_sites[v["id"]].coalition == side]
            for n, v in groups:
                s = st.sam_sites[v["id"]]
                if s.role == "ewr":
                    ewr += unit_names(n, int(v.get("units", 1)))
                elif s.role == "sam":
                    sites.append({"group": n, "template": s.template})
            big = [(n, st.sam_sites[v["id"]]) for n, v in groups
                   if st.sam_sites[v["id"]].role == "sam" and st.sam_sites[v["id"]].range_km >= 25]
            small = [(n, st.sam_sites[v["id"]]) for n, v in groups
                     if st.sam_sites[v["id"]].role == "sam" and st.sam_sites[v["id"]].template in SHORAD]
            for bn, b in big:
                for sn, sm in small:
                    if geo.dist_km((b.lat, b.lon), (sm.lat, sm.lon)) <= 15:
                        pd_pairs.append({"site": bn, "defender": sn})
            for n, v in man.items():
                if v.get("kind") != "flight" or v.get("coalition") is None:
                    continue
                if v["coalition"] == side and v.get("task") == "AWACS":
                    awacs += unit_names(n, int(v.get("units", 1)))
                if v["coalition"] != side and v.get("aircraft") in JAMMER_TYPES and not v.get("player") \
                        and not v.get("clients"):
                    jammers += unit_names(n, int(v.get("units", 1)))
            nets.append({"name": side.upper(), "sites": sites, "ewr_units": ewr, "point_defence": pd_pairs,
                         "awacs_units": awacs, "jammer_units": jammers})
        cfg["skynet"] = {**p, "networks": nets}
    if is_on(settings, "hound"):
        p = params(settings, "hound")
        pre = []
        if p.get("prebriefed"):
            pre = [n for n, v in man.items() if v.get("kind") == "sam_site" and v.get("id") in st.sam_sites
                   and st.sam_sites[v["id"]].coalition != player and st.sam_sites[v["id"]].known
                   and st.sam_sites[v["id"]].role in ("sam", "ewr")]
        cfg["hound"] = {**p, "side": 2 if player == "blue" else 1, "prebriefed": pre}
    if is_on(settings, "growler"):
        cfg["growler"] = {**params(settings, "growler"), "prefix": GROWLER_PREFIX}
    return cfg


def files_for_mission(settings, tmp: Path) -> Dict[str, List[Path]]:
    """{'before': [...] (needed by later scripts: MIST), 'after': [...] (after SORTIE's own scripts),
    'delayed': [...] (loaded a few seconds in)} for the add-ons that are on."""
    before, after, delayed = [], [], []
    if is_on(settings, "skynet"):
        before.append(VENDOR / "mist.lua")
    if is_on(settings, "splash"):
        after.append(patched_splash(settings, tmp))
    if is_on(settings, "skynet"):
        after.append(VENDOR / "skynet-iads-compiled.lua")
    if is_on(settings, "hound"):
        after.append(VENDOR / "HoundElint.lua")
    if is_on(settings, "growler"):
        delayed.append(VENDOR / "Growler_AEA.lua")
    return {"before": before, "after": after, "delayed": delayed}


def growler_types(settings) -> List[str]:
    if not is_on(settings, "growler"):
        return []
    return [t.strip() for t in str(params(settings, "growler").get("jammer_types", "")).split(",") if t.strip()]
