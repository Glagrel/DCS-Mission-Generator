"""Mission builder: campaign state + ATO -> .miz (pydcs)."""
from __future__ import annotations

import logging
import uuid
import zipfile
import shutil
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import dcs
from dcs import countries as dcs_countries
from dcs.coalition import Coalition
from dcs.weather import Wind
from pydantic import BaseModel, Field

from .. import config, terrain
from ..atc import luacfg
from ..models_ato import Ato
from ..state import State
from . import briefing, budget, clock, forces, kneeboard, loadouts, scripts, slots, warehouses
from .flights import FlightBuilder

log = logging.getLogger("sortie.mission")
RUNTIME_SUBDIR = "Missions\\SORTIE\\runtime\\"
EVENTS_FILE = "events.jsonl"


class BuildError(RuntimeError):
    pass


class BuildResult(BaseModel):
    ok: bool = True
    path: str
    filename: str
    sortie_id: str
    warnings: List[str] = Field(default_factory=list)
    manifest: Dict[str, Any] = Field(default_factory=dict)
    selection: Dict[str, Any] = Field(default_factory=dict)
    briefing: Dict[str, Any] = Field(default_factory=dict)
    scripts: List[str] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)
    extra_paths: List[str] = Field(default_factory=list)      # copies (dedicated server folder)
    slots: List[Dict[str, Any]] = Field(default_factory=list)  # human seats in the mission


def _country_classes() -> Dict[str, type]:
    return {c.name: c for c in dcs_countries.country_dict.values()}


def _setup_coalitions(m, st: State) -> None:
    classes = _country_classes()
    for side in ("blue", "red"):
        co = Coalition(side)
        for name in st.meta.countries.get(side, []):
            co.add_country(classes[name]())
        be = st.meta.bullseye.get(side)
        if be:
            p = terrain.to_point(m.terrain, be.lat, be.lon)
            co.set_bullseye({"x": p.x, "y": p.y})
        m.coalition[side] = co


def _setup_weather(m, w: Dict[str, Any]) -> None:
    if not w:
        return
    wx = m.weather
    d, s = int(w.get("wind_dir", 0)), float(w.get("wind_ms", 0))
    wx.wind_at_ground = Wind(d, s)
    wx.wind_at_2000 = Wind((d + 15) % 360, round(s * 1.6, 1))
    wx.wind_at_8000 = Wind((d + 30) % 360, round(s * 2.4, 1))
    wx.season_temperature = float(w.get("temp_c", 20))
    wx.clouds_base = int(w.get("cloud_base_m", 2000))
    wx.clouds_density = int(w.get("cloud_density", 0))
    wx.clouds_thickness = int(w.get("cloud_thickness_m", 200))
    wx.visibility_distance = int(float(w.get("visibility_km", 80)) * 1000)


def mission_filename(st: State) -> str:
    return f"SORTIE_{st.meta.template_id}_T{st.meta.turn:03d}.miz"


def build_mission(st: State, ato: Ato, reason: str, settings: config.Settings,
                  out_dir: Optional[Path] = None, with_moose: Optional[bool] = None) -> BuildResult:
    """Write the .miz for the player's assigned sortie. Raises BuildError on failure."""
    if not ato.player_flight_id:
        raise BuildError("no player flight assigned this cycle: " + reason)
    if not terrain.is_supported(st.meta.terrain):
        raise BuildError(f"terrain {st.meta.terrain} is not supported by the installed pydcs")
    d = config.defaults(settings)
    profile = st.meta.profile if st.meta.profile in config.PROFILE_NAMES else config.resolve_profile(settings)
    limits = config.profile_limits(profile, settings)
    logistics = d["logistics"]
    diff = d["difficulty"][st.meta.difficulty]
    warnings: List[str] = []
    if terrain.is_fallback(st.meta.terrain):
        warnings.append(f"Terrain {st.meta.terrain} is not in pydcs; built on "
                        f"{terrain.resolve(st.meta.terrain)[0]} instead (see docs/DECISIONS.md).")
    loadouts.configure(config.resolved_install(settings), config.resolved_saved_games(settings))
    try:
        m = dcs.Mission(terrain.new_terrain(st.meta.terrain))
        _setup_coalitions(m, st)
        hot = settings.player_start == "hot"
        t0 = clock.mission_t0(ato, d, hot)          # fast-forward: start just before the player's start-up
        m.start_time = (st.now + timedelta(seconds=t0)).replace(tzinfo=timezone.utc)
        _setup_weather(m, st.meta.weather)
        warehouses.apply_to_mission(m, st, logistics)
        sel = budget.select(st, ato, limits, t0)
        man = forces.Manifest()
        ships = forces.add_naval(m, st, sel, man)
        carrier_units: Dict[str, str] = {}
        for nid, sg in ships.items():
            base_id = st.naval_groups[nid].airbase_id
            if base_id and base_id in st.airbases:
                m.warehouses.warehouses[int(sg.units[0].id)] = warehouses.carrier_warehouse(
                    st.airbases[base_id], logistics)
                carrier_units[nid] = sg.units[0].name
        forces.add_sam_sites(m, st, sel, man)
        forces.add_ground_units(m, st, sel, man)
        forces.add_supply_nodes(m, st, sel, man)
        forces.add_convoys(m, st, sel, man)
        coop, extra = max(1, int(settings.coop_slots)), max(0, int(settings.coop_extra_slots))
        multiplayer = slots.is_multiplayer(coop, extra)
        seats = slots.allocate(st, ato, sel.flights, coop, extra, settings.coop_modules, t0)
        missing = slots.unowned_extra(extra, seats, ato.player_flight_id)
        if missing:
            warnings.append(f"{missing} of {extra} extra co-op seats could not be placed: no friendly flight "
                            "on the ground this cycle flies an aircraft from the co-op module list.")
        skills = {"friendly": diff["friendly_skill"], "enemy": diff["enemy_skill"]}
        fb = FlightBuilder(m, st, ato, sel, man, ships, seats, multiplayer, skills, warnings, t0, d, hot)
        fb.build_all()
        moose_on = scripts.MOOSE_FILE.is_file() if with_moose is None else (with_moose and scripts.MOOSE_FILE.is_file())
        for entry in fb.carrier_support:            # MOOSE's RESCUEHELO spawns from a late-activated template
            entry["moose"] = moose_on
            if moose_on:
                m.find_group(entry["group"]).late_activation = True
        slot_list = slots.summary(st, ato, seats, man)
        brief = briefing.build(st, ato, reason, t0=t0, units=settings.units, slots=slot_list)
        text = briefing.text(st, brief)
        kneeboard.attach(m, st, ato, brief, slot_list, t0, settings.units, warnings)
        m.set_sortie_text(f"SORTIE cycle {st.meta.turn}: {brief['mission']} - {brief['target']['name']}")
        m.set_description_text(text)
        side = st.meta.player_side
        (m.set_description_bluetask_text if side == "blue" else m.set_description_redtask_text)(
            brief["objective"])
        sortie_id = uuid.uuid4().hex[:12]
        player_group = budget.gname("flt", ato.player_flight_id)
        cfg = {
            "version": 1, "campaign": st.meta.name, "turn": st.meta.turn, "sortie": sortie_id,
            "player_side": 2 if side == "blue" else 1, "player_group": player_group,
            "runtime_subdir": RUNTIME_SUBDIR, "events_file": EVENTS_FILE,
            "snapshot_interval": 30, "spawn_m": limits["spawn_km"] * 1000.0,
            "despawn_m": limits["despawn_km"] * 1000.0, "manifest": dict(man),
            "late_groups": [n for n, v in man.items() if v.get("late")],
            "client_groups": [r["group"] for r in slot_list if r["group"]],
            "carrier_support": fb.carrier_support,
            "event_dirs": [str(p.parent) + "\\" for p in config.event_file_candidates(settings)[:2]],
            "warehouses": warehouses.lua_table(st, logistics, carrier_units),
            "atc": luacfg.build(st, ato, settings, man),
        }
        names = scripts.attach(m, cfg, bool(cfg["atc"].get("enabled")), with_moose)
        out_dir = Path(out_dir) if out_dir else config.resolved_output_dir(settings)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / mission_filename(st)
        m.save(str(path))
        kb_pages = kneeboard.write(m, path)
        extra_paths: List[str] = []
        server_dir = config.server_output_dir(settings)
        if server_dir is not None and server_dir.resolve() != out_dir.resolve():
            try:
                server_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, server_dir / path.name)
                extra_paths.append(str(server_dir / path.name))
            except OSError as exc:
                warnings.append(f"Could not copy the mission to the server folder {server_dir}: {exc}")
    except BuildError:
        raise
    except Exception as exc:
        log.exception("mission build failed")
        raise BuildError(f"mission build failed: {exc}") from exc
    problems = verify_miz(path, names)
    if problems:
        raise BuildError("generated mission failed verification: " + "; ".join(problems))
    warnings = list(dict.fromkeys(warnings))            # same note from several flights: say it once
    if sel.dropped:
        warnings.append("Performance limits left out: " + ", ".join(f"{v} {k}" for k, v in sel.dropped.items()))
    stats = {"aircraft": sel.total_aircraft, "peak_airborne": sel.aircraft, "flights": len(sel.flights),
             "naval_groups": len(sel.naval_groups), "t0_s": round(t0),
             "start_time": (st.now + timedelta(seconds=t0)).strftime("%H:%M"),
             "human_seats": sum(r["seats"] for r in slot_list), "multiplayer": multiplayer,
             "player_start": "hot" if hot else "cold",
             "kneeboard_pages": len(kb_pages),
             "ground_groups": len(sel.ground_units) + len(sel.sam_sites) + len(sel.routes),
             "static_groups": sum(1 for v in man.values() if v["kind"] == "supply_node"),
             "profile": profile, "coop_slots": coop, "size_kb": round(path.stat().st_size / 1024, 1)}
    log.info("mission written %s", path, extra={"turn": st.meta.turn, **stats})
    return BuildResult(path=str(path), filename=path.name, sortie_id=sortie_id, warnings=warnings,
                       manifest=dict(man), selection=sel.model_dump(), briefing=brief, scripts=names, stats=stats,
                       extra_paths=extra_paths, slots=slot_list)


def verify_miz(path: Path, script_names: List[str]) -> List[str]:
    """Structural checks that need no DCS: archive members, scripts, trigger, reload by pydcs."""
    problems: List[str] = []
    try:
        with zipfile.ZipFile(path) as z:
            members = set(z.namelist())
            for need in ("mission", "warehouses", "options", "l10n/DEFAULT/dictionary", "l10n/DEFAULT/mapResource"):
                if need not in members:
                    problems.append(f"missing {need}")
            for n in script_names:
                if f"l10n/DEFAULT/{n}" not in members:
                    problems.append(f"script {n} not embedded")
            mission = z.read("mission").decode("utf-8", "replace")
            if mission.count("a_do_script_file") < len(script_names):
                problems.append("DO SCRIPT FILE actions missing from trigger rules")
            if '"triggerStart"' not in mission:
                problems.append("no MISSION START trigger")
        dcs.Mission().load_file(str(path))
    except Exception as exc:
        problems.append(f"unreadable .miz: {exc}")
    return problems
