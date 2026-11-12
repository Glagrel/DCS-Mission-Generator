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
        """The preferred event file (others are watched too: see config.event_file_candidates)."""
        return config.event_file_candidates(self.settings)[0]

    def _tail_list(self, cid: str) -> List[watcher.EventTail]:
        """One tail per place the mission may write to (client, dedicated server, %TEMP%)."""
        out = []
        for i, path in enumerate(config.event_file_candidates(self.settings)):
            key = f"{cid}|{path}"
            if key not in self._tails:
                self._tails[key] = watcher.EventTail(path, self.store, f"events:{cid}:{i}")
            out.append(self._tails[key])
        return out

    # -- campaign ----------------------------------------------------------------------------
    def new_campaign(self, opt: CareerOptions) -> str:
        return create_campaign(self.store, theater.load(opt.theater_id), opt, self.settings)

    def plan(self, cid: str, st: Optional[State] = None) -> Dict[str, Any]:
        """Make sure the current turn has an ATO with the player's assignment. Idempotent."""
        st = st or self.state(cid)
        if st.meta.status != "active":
            return {"assigned": False, "reason": f"campaign is over ({st.meta.status})"}
        if st.ato is not None and st.ato.version < planner.PLAN_VERSION and self._replannable(st):
            log.info("re-planning cycle %s: saved ATO is from an older planner", st.meta.turn)
            st.ato = None                             # an unflown plan from an older version
        if st.ato is None:
            st.ato = planner.generate_ato(st, self.d)
            res = assign.assign_player(st, st.ato, self.d, max(1, self.settings.coop_slots))
            st.ato.support["player_reason"] = res["reason"]
            st.sortie = SortieResult(id=f"sortie-{st.meta.turn}", turn=st.meta.turn)
            save_state(self.store, cid, st)
            self.store.log(cid, st.meta.turn, "assignment", {"reason": res["reason"],
                                                             "flight": res.get("flight_id")})
        from .mission import clock
        slot_list = (st.sortie.summary.get("slots") if st.sortie else None) or []
        nav = self._home_nav(st)
        return briefing.build(st, st.ato, st.ato.support.get("player_reason", ""),
                              t0=clock.mission_t0(st.ato, self.d, self.settings.player_start == "hot"),
                              units=self.settings.units, slots=slot_list, nav=nav)

    def _home_nav(self, st: State) -> Dict[str, Any]:
        from . import navaids, terrain
        _, flt = st.ato.find_flight(st.ato.player_flight_id or "") if st.ato else (None, None)
        if flt is None:
            return {}
        base = st.airbases[st.squadrons[flt.squadron_id].airbase_id]
        try:
            tobj = terrain.new_terrain(st.meta.terrain) if base.kind != "carrier" else None
            return navaids.home_nav(st, base, config.resolved_install(self.settings), tobj)
        except Exception as exc:                      # nav data is a nicety, never a blocker
            log.warning("home nav data unavailable: %s", exc)
            return {}

    @staticmethod
    def _replannable(st: State) -> bool:
        """A plan from an older planner may be replaced as long as the sortie has not been flown.
        (Packages an older version already resolved before launch keep their effects.)"""
        if st.sortie and st.sortie.state not in ("planned", "built"):
            return False
        return not any(f.status == "simulated" for _, f in st.ato.flights())

    def generate_mission(self, cid: str, out_dir: Optional[Path] = None,
                         with_moose: Optional[bool] = None) -> builder.BuildResult:
        st = self.state(cid)
        self.plan(cid, st)
        if st.pilot and st.pilot.status in ("kia", "pow", "mia"):
            raise ServiceError(f"career is over: pilot is {st.pilot.status.upper()}")
        self._resolve_before_launch(st)
        try:
            res = builder.build_mission(st, st.ato, st.ato.support.get("player_reason", ""), self.settings,
                                        out_dir, with_moose)
        except builder.BuildError as exc:
            raise ServiceError(str(exc)) from exc
        st.sortie = SortieResult(id=f"sortie-{st.meta.turn}", turn=st.meta.turn, state="built",
                                 miz_path=res.path,
                                 summary={"manifest": res.manifest, "sortie_id": res.sortie_id,
                                          "player_group": builder.budget.gname("flt", st.ato.player_flight_id),
                                          "warnings": res.warnings, "stats": res.stats, "slots": res.slots,
                                          "extra_paths": res.extra_paths})
        save_state(self.store, cid, st)             # also stores callsigns DCS actually assigned
        self.store.clear_events(cid, st.meta.turn)
        self.store.log(cid, st.meta.turn, "mission", {"path": res.path, "stats": res.stats})
        return res

    def _resolve_before_launch(self, st: State) -> None:
        """The mission starts at the start-up time of the player flight. Packages that are already
        home by then are fought out now, so their results (dead SAMs, losses, damage) are in the
        mission that gets built."""
        from .mission import clock
        from .sim import airwar
        ato = st.ato
        if not ato or not ato.player_flight_id:
            return
        t0 = clock.mission_t0(ato, self.d, self.settings.player_start == "hot")
        rng = st.rng("airwar-pre")
        lines = list(ato.support.get("pre_mission", []))
        for pkg in sorted(ato.packages, key=lambda p: (p.tot_s, p.id)):
            if pkg.id == ato.player_package_id or not pkg.flights:
                continue
            if any(f.status != "planned" or clock.phase(f, t0) != clock.DONE for f in pkg.flights):
                continue
            results = airwar.resolve_package(st, ato, pkg, self.d, rng, set())
            if pkg.coalition == st.meta.player_side and results:
                lost = sum(r.lost for r in results)
                ok = max(r.success for r in results)
                lines.append(f"{pkg.id} {pkg.mission} on {pkg.target.name}: "
                             + ("successful" if ok >= 0.5 else "little effect")
                             + (f", {lost} aircraft lost" if lost else ""))
        ato.support["pre_mission"] = lines

    # -- live feed ---------------------------------------------------------------------------
    def poll_live(self, cid: str) -> Dict[str, Any]:
        """Read new lines of events.jsonl, store those of this turn's sortie, return feed lines."""
        st = self.state(cid)
        sortie_id = (st.sortie.summary.get("sortie_id") if st.sortie else None)
        tails = self._tail_list(cid)
        new, tail = [], tails[0]
        for t in tails:
            got = [e for e in t.poll() if sortie_id and str(e.get("id", "")).startswith(sortie_id + "-")]
            if got:
                new, tail = new + got, t
        if not new:
            tail = next((t for t in tails if t.path.is_file()), tails[0])
        if new:
            self.store.add_events(cid, st.meta.turn, new)
        feed = [x for x in (aar.timeline_entry(e) for e in new) if x]
        snap = next((e for e in reversed(new) if e.get("ev") == "snapshot"), None)
        return {"events": feed, "snapshot": snap, "count": len(self.store.events(cid, st.meta.turn)),
                "malformed": sum(t.malformed for t in tails), "file": str(tail.path),
                "exists": tail.path.is_file(), "watching": [str(t.path) for t in tails]}

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
        if not events and sortie_id:
            # no event file (host not desanitised?): look for this sortie in the DCS logs
            for logf in config.dcs_log_candidates(self.settings):
                found = [e for e in watcher.parse_dcs_log(logf)
                         if str(e.get("id", "")).startswith(sortie_id + "-")]
                if found:
                    self.store.add_events(cid, st.meta.turn, found)
                    log.info("read %d events from %s", len(found), logf)
            events = watcher.latest_run(self.store.events(cid, st.meta.turn))
        flown: List[str] = []
        if events and sortie_id:
            ingest.ingest(st, st.ato, st.sortie, events, self.d)
            flown = list(st.sortie.flights)
        elif not allow_empty:
            raise ServiceError("no mission events found for this sortie in the event file or in dcs.log "
                               "(client or server). Make sure the mission you flew is the one generated "
                               "last, or use 'skip sortie'.")
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
