"""Application service: the campaign loop used by the web API, the CLI and the tests.

plan -> generate_mission -> (fly in DCS; poll_live) -> debrief -> next turn.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config, theater
from .ato import assign, planner
from .campaign import CareerOptions, create_campaign
from .db import Store
from .debrief import ingest, reassign
from .mission import briefing, builder, loadouts
from .models_ato import SortieResult
from .runtime import aar, watcher
from .sim import turn as simturn
from .state import State, load_state, save_state

log = logging.getLogger("sortie.service")


class ServiceError(RuntimeError):
    pass


class Service:
    def __init__(self, store: Store, settings: config.Settings) -> None:
        self.store, self.settings = store, settings
        self._tails: Dict[str, watcher.EventTail] = {}
        loadouts.configure_from_settings(settings)

    # -- helpers -----------------------------------------------------------------------------
    @property
    def d(self) -> Dict[str, Any]:
        return config.defaults(self.settings)

    def state(self, cid: str) -> State:
        try:
            return load_state(self.store, cid)
        except KeyError as exc:
            raise ServiceError(str(exc)) from exc

    def events_path(self) -> Path:
        return config.resolved_runtime_dir(self.settings) / builder.EVENTS_FILE

    def _tail(self, cid: str) -> watcher.EventTail:
        path = self.events_path()
        t = self._tails.get(cid)
        if t is None or t.path != path:
            t = self._tails[cid] = watcher.EventTail(path, self.store, f"events:{cid}")
        return t

    # -- campaign ----------------------------------------------------------------------------
    def new_campaign(self, opt: CareerOptions) -> str:
        return create_campaign(self.store, theater.load(opt.theater_id), opt, self.settings)

    def plan(self, cid: str, st: Optional[State] = None) -> Dict[str, Any]:
        """Make sure the current turn has an ATO with the player's assignment. Idempotent."""
        st = st or self.state(cid)
        if st.meta.status != "active":
            return {"assigned": False, "reason": f"campaign is over ({st.meta.status})"}
        if st.ato is None:
            st.ato = planner.generate_ato(st, self.d)
            res = assign.assign_player(st, st.ato, self.d, max(1, self.settings.coop_slots))
            st.ato.support["player_reason"] = res["reason"]
            st.sortie = SortieResult(id=f"sortie-{st.meta.turn}", turn=st.meta.turn)
            save_state(self.store, cid, st)
            self.store.log(cid, st.meta.turn, "assignment", {"reason": res["reason"],
                                                             "flight": res.get("flight_id")})
        return briefing.build(st, st.ato, st.ato.support.get("player_reason", ""))

    def generate_mission(self, cid: str, out_dir: Optional[Path] = None,
                         with_moose: Optional[bool] = None) -> builder.BuildResult:
        st = self.state(cid)
        self.plan(cid, st)
        if st.pilot and st.pilot.status in ("kia", "pow", "mia"):
            raise ServiceError(f"career is over: pilot is {st.pilot.status.upper()}")
        try:
            res = builder.build_mission(st, st.ato, st.ato.support.get("player_reason", ""), self.settings,
                                        out_dir, with_moose)
        except builder.BuildError as exc:
            raise ServiceError(str(exc)) from exc
        st.sortie = SortieResult(id=f"sortie-{st.meta.turn}", turn=st.meta.turn, state="built",
                                 miz_path=res.path,
                                 summary={"manifest": res.manifest, "sortie_id": res.sortie_id,
                                          "player_group": builder.budget.gname("flt", st.ato.player_flight_id),
                                          "warnings": res.warnings, "stats": res.stats})
        save_state(self.store, cid, st)             # also stores callsigns DCS actually assigned
        self.store.clear_events(cid, st.meta.turn)
        self.store.log(cid, st.meta.turn, "mission", {"path": res.path, "stats": res.stats})
        return res

    # -- live feed ---------------------------------------------------------------------------
    def poll_live(self, cid: str) -> Dict[str, Any]:
        """Read new lines of events.jsonl, store those of this turn's sortie, return feed lines."""
        st = self.state(cid)
        sortie_id = (st.sortie.summary.get("sortie_id") if st.sortie else None)
        tail = self._tail(cid)
        new = [e for e in tail.poll() if sortie_id and str(e.get("id", "")).startswith(sortie_id + "-")]
        if new:
            self.store.add_events(cid, st.meta.turn, new)
        feed = [x for x in (aar.timeline_entry(e) for e in new) if x]
        snap = next((e for e in reversed(new) if e.get("ev") == "snapshot"), None)
        return {"events": feed, "snapshot": snap, "count": len(self.store.events(cid, st.meta.turn)),
                "malformed": tail.malformed, "file": str(tail.path), "exists": tail.path.is_file()}

    def import_events(self, cid: str, path: Path) -> int:
        """Load an events.jsonl (or a dcs.log with SORTIE_EVT lines) for the current sortie."""
        st = self.state(cid)
        path = Path(path)
        events = watcher.parse_dcs_log(path) if path.suffix.lower() == ".log" else watcher.read_all(path)
        sortie_id = st.sortie.summary.get("sortie_id") if st.sortie else None
        events = [e for e in events if sortie_id and str(e.get("id", "")).startswith(sortie_id + "-")]
        return self.store.add_events(cid, st.meta.turn, events)

    # -- debrief / turn end --------------------------------------------------------------------
    def debrief(self, cid: str, allow_empty: bool = False) -> Dict[str, Any]:
        """Ingest this turn's mission events, resolve the rest of the war, advance to next turn."""
        st = self.state(cid)
        if st.ato is None or st.sortie is None:
            raise ServiceError("nothing to debrief: no mission has been generated this cycle")
        self.poll_live(cid)
        sortie_id = st.sortie.summary.get("sortie_id")
        events = watcher.latest_run(self.store.events(cid, st.meta.turn))
        flown: List[str] = []
        if events and sortie_id:
            ingest.ingest(st, st.ato, st.sortie, events, self.d)
            flown = list(st.sortie.flights)
        elif not allow_empty:
            raise ServiceError("no mission events found for this sortie. Fly the mission first (and check "
                               "that MissionScripting.lua is desanitised), or use 'skip sortie'.")
        else:
            st.sortie.state = "skipped"
        return self._finish_turn(cid, st, flown)

    def skip(self, cid: str) -> Dict[str, Any]:
        """Stand down: the whole ATO, including the player's flight, is resolved abstractly."""
        st = self.state(cid)
        self.plan(cid, st)
        st.sortie = st.sortie or SortieResult(id=f"sortie-{st.meta.turn}", turn=st.meta.turn)
        st.sortie.state = "skipped"
        return self._finish_turn(cid, st, [])

    def _finish_turn(self, cid: str, st: State, flown: List[str]) -> Dict[str, Any]:
        turn = st.meta.turn
        sortie, ato = st.sortie, st.ato
        save_state(self.store, cid, st)               # keep this turn's ATO/sortie as a record
        report = simturn.end_turn(st, self.d, flown)
        transfer = reassign.consider(st, self.d)
        if transfer:
            report["transfer"] = transfer
        save_state(self.store, cid, st)
        if ato:                                       # the finished cycle's ATO, now fully resolved
            self.store.put(cid, "ato", ato)
        self.store.put(cid, "sortie", sortie)
        result = {
            "turn": turn, "state": sortie.state, "mission_success": sortie.mission_success,
            "player": sortie.player, "flight_time_s": sortie.flight_time_s,
            "flights": {k: v.model_dump() for k, v in sortie.flights.items()},
            "summary": {k: v for k, v in sortie.summary.items() if k != "manifest"},
            "entity_damage": sortie.entity_damage, "timeline": sortie.timeline, "war": report,
            "pilot": st.pilot.model_dump() if st.pilot else None, "transfer": transfer,
            "task": sortie.summary.get("task"), "target": sortie.summary.get("target"),
            "next": {"turn": st.meta.turn, "date": st.meta.date, "status": st.meta.status},
        }
        self.store.log(cid, turn, "debrief", result)
        return result

    def last_debrief(self, cid: str) -> Optional[Dict[str, Any]]:
        rows = self.store.history(cid, "debrief", limit=1)
        return rows[0] if rows else None
