"""FastAPI application: JSON API + static single-page GUI."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import config, measure, paths, sanitize, terrain, theater, units
from ..campaign import CampaignError, CareerOptions, owned
from ..db import Store
from ..mission import scripts
from ..service import Service, ServiceError
from . import views

log = logging.getLogger("sortie.web")
STATIC = Path(__file__).resolve().parent / "static"
CODE_DIR = Path(__file__).resolve().parent.parent


def code_stamp() -> float:
    """Newest modification time of SORTIE's own source files. The running server keeps the
    code it started with, so a newer stamp on disk means it has to be restarted."""
    newest = 0.0
    for pattern in ("*.py", "*/*.py", "lua/*.lua", "web/static/*"):
        for f in CODE_DIR.glob(pattern):
            try:
                newest = max(newest, f.stat().st_mtime)
            except OSError:
                pass
    return newest


class SanitizeRequest(BaseModel):
    path: str
    action: str                      # desanitize | restore


class SettingsPatch(BaseModel):
    saved_games: Optional[str] = None
    dcs_install: Optional[str] = None
    output_dir: Optional[str] = None
    owned_modules: Optional[List[str]] = None
    profile: Optional[str] = None
    coop_slots: Optional[int] = None
    coop_extra_slots: Optional[int] = None
    coop_modules: Optional[List[str]] = None
    server_saved_games: Optional[str] = None
    save_to_server: Optional[bool] = None
    units: Optional[str] = None
    player_start: Optional[str] = None
    atc_enabled: Optional[bool] = None
    voice: Optional[str] = None
    srs_path: Optional[str] = None
    srs_port: Optional[int] = None
    piper_voice: Optional[str] = None
    google_credentials: Optional[str] = None


def create_app(settings: Optional[config.Settings] = None, settings_file: Path = config.SETTINGS_FILE,
               store: Optional[Store] = None) -> FastAPI:
    settings = settings or config.load_settings(settings_file)
    store = store or Store(settings.db_path)
    svc = Service(store, settings)
    app = FastAPI(title="SORTIE", version="0.1.0")
    app.state.svc = svc
    started_stamp = code_stamp()

    @app.exception_handler(Exception)
    async def unhandled(request, exc):
        """Never answer with a bare 'Internal Server Error': log the traceback and say what failed."""
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        hint = " SORTIE's files changed since this window was started: close it and start SORTIE again." \
            if code_stamp() > started_stamp + 1 else ""
        return JSONResponse(status_code=500, content={
            "detail": f"Internal error ({type(exc).__name__}: {exc}).{hint} Details are in campaigns\\sortie.log.jsonl."})

    lock = threading.RLock()     # one SQLite connection: serialise requests (the GUI fetches in parallel)

    def guard(fn, *a, **kw):
        try:
            with lock:
                return fn(*a, **kw)
        except (ServiceError, CampaignError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # -- environment / settings -------------------------------------------------------------
    @app.get("/api/status")
    def status() -> Dict[str, Any]:
        s = svc.settings
        sg, inst = config.resolved_saved_games(s), config.resolved_install(s)
        ram = config.total_ram_gb()
        return {
            "saved_games": str(sg) if sg else None, "saved_games_auto": s.saved_games is None,
            "dcs_install": str(inst) if inst else None, "dcs_install_auto": s.dcs_install is None,
            "output_dir": str(config.resolved_output_dir(s)), "events_file": str(svc.events_path()),
            "ram_gb": round(ram, 1), "profile_auto": config.profile_for_ram(ram, config.defaults(s)),
            "profile": config.resolve_profile(s), "profiles": config.defaults(s)["profiles"],
            "moose": scripts.MOOSE_FILE.is_file(), "moose_path": str(scripts.MOOSE_FILE),
            "terrains": {k: terrain.is_supported(k) for k in terrain.TERRAINS},
            "difficulties": list(config.defaults(s)["difficulty"]), "voices": list(config.VOICE_ENGINES),
            "units": measure.labels(s.units),
            "restart_needed": code_stamp() > started_stamp + 1,
            "server_output_dir": str(config.server_output_dir(s)) if config.server_output_dir(s) else None,
            "server_candidates": [str(p) for p in paths.server_saved_games_candidates()],
            "event_files": [str(p) for p in config.event_file_candidates(s)],
        }

    @app.get("/api/settings")
    def get_settings() -> Dict[str, Any]:
        return svc.settings.model_dump()

    @app.put("/api/settings")
    def put_settings(patch: SettingsPatch) -> Dict[str, Any]:
        data = patch.model_dump(exclude_unset=True)
        if "profile" in data and data["profile"] not in ("auto",) + config.PROFILE_NAMES:
            raise HTTPException(400, "profile must be auto, light, standard or heavy")
        if "voice" in data and data["voice"] not in config.VOICE_ENGINES:
            raise HTTPException(400, f"voice must be one of {config.VOICE_ENGINES}")
        if "coop_slots" in data and not 1 <= int(data["coop_slots"]) <= 4:
            raise HTTPException(400, "coop_slots must be 1..4")
        if "coop_extra_slots" in data and not 0 <= int(data["coop_extra_slots"]) <= 12:
            raise HTTPException(400, "coop_extra_slots must be 0..12")
        if "units" in data and data["units"] not in measure.SYSTEMS:
            raise HTTPException(400, f"units must be one of {measure.SYSTEMS}")
        if "player_start" in data and data["player_start"] not in ("cold", "hot"):
            raise HTTPException(400, "player_start must be cold or hot")
        if data.get("coop_modules") is not None:
            bad = [m for m in data["coop_modules"] if m not in units.flyable_modules()]
            if bad:
                raise HTTPException(400, f"not flyable modules: {bad}")
        if "owned_modules" in data and data["owned_modules"] is not None:
            bad = [m for m in data["owned_modules"] if m not in units.flyable_modules()]
            if bad:
                raise HTTPException(400, f"not flyable modules: {bad}")
        for k in ("saved_games", "dcs_install", "output_dir", "server_saved_games"):
            if k in data and data[k] == "":
                data[k] = None                           # empty string = back to auto-detect
        new = svc.settings.model_copy(update=data)
        config.save_settings(new, settings_file)
        svc.settings = new
        from ..mission import loadouts
        loadouts.configure_from_settings(new)
        return new.model_dump()

    @app.get("/api/desanitize")
    def desanitize_status() -> List[Dict[str, Any]]:
        """Each DCS install in use and whether mission scripts may write files there."""
        return sanitize.installs(svc.settings)

    @app.post("/api/desanitize")
    def desanitize_apply(req: SanitizeRequest) -> Dict[str, Any]:
        """Runs tools/install_desanitize.ps1 for one detected install - only ever on this click."""
        if req.action not in ("desanitize", "restore"):
            raise HTTPException(400, "action must be desanitize or restore")
        known = {i["path"].rstrip("\\/").lower() for i in sanitize.installs(svc.settings)}
        if req.path.rstrip("\\/").lower() not in known:
            raise HTTPException(400, "not a detected DCS install")
        res = sanitize.apply(Path(req.path), undo=req.action == "restore")
        if not res["ok"]:
            raise HTTPException(400, "Could not change MissionScripting.lua. " + res["output"][-600:])
        return res

    @app.get("/api/modules")
    def modules() -> List[Dict[str, Any]]:
        mine = set(owned(svc.settings))
        return [{"id": m, "year": units.year_of(m), "owned": m in mine,
                 "helicopter": units.is_helicopter(m)} for m in units.flyable_modules()]

    @app.get("/api/theaters")
    def theaters() -> List[Dict[str, Any]]:
        return [views.theater_card(t, owned(svc.settings)) for t in theater.list_theaters()]

    # -- campaigns -------------------------------------------------------------------------------
    @app.get("/api/campaigns")
    def campaigns() -> List[Dict[str, Any]]:
        return guard(store.list_campaigns)

    @app.post("/api/campaigns")
    def new_campaign(opt: CareerOptions) -> Dict[str, Any]:
        return {"id": guard(svc.new_campaign, opt)}

    @app.delete("/api/campaigns/{cid}")
    def delete_campaign(cid: str) -> Dict[str, Any]:
        guard(store.delete_campaign, cid)
        return {"deleted": cid}

    @app.get("/api/campaigns/{cid}/overview")
    def overview(cid: str):
        return views.overview(guard(svc.state, cid), svc.d)

    @app.get("/api/campaigns/{cid}/map")
    def map_(cid: str):
        return views.map_data(guard(svc.state, cid))

    @app.get("/api/campaigns/{cid}/ato")
    def ato(cid: str):
        guard(svc.plan, cid)
        return views.ato_view(guard(svc.state, cid))

    @app.get("/api/campaigns/{cid}/briefing")
    def brief(cid: str):
        return guard(svc.plan, cid)

    @app.get("/api/campaigns/{cid}/roster")
    def roster(cid: str):
        return views.roster(guard(svc.state, cid), svc.d)

    @app.get("/api/campaigns/{cid}/career")
    def career(cid: str):
        return views.career_view(guard(svc.state, cid))

    @app.get("/api/campaigns/{cid}/logistics")
    def logistics(cid: str):
        return views.logistics(guard(svc.state, cid))

    @app.get("/api/campaigns/{cid}/history")
    def history(cid: str, kind: Optional[str] = None, limit: int = 100):
        return guard(store.history, cid, kind, None, min(limit, 500))

    # -- the loop ----------------------------------------------------------------------------------
    @app.post("/api/campaigns/{cid}/mission")
    def generate(cid: str):
        """Generate Next Mission: the ATO assigns the sortie, the .miz is written."""
        res = guard(svc.generate_mission, cid)
        return {"ok": True, "path": res.path, "filename": res.filename, "warnings": res.warnings,
                "stats": res.stats, "scripts": res.scripts, "briefing": res.briefing,
                "extra_paths": res.extra_paths, "slots": res.slots,
                "sanitized": sanitize.needs_attention(svc.settings)}

    @app.get("/api/campaigns/{cid}/live")
    def live(cid: str):
        return guard(svc.poll_live, cid)

    @app.post("/api/campaigns/{cid}/debrief")
    def debrief(cid: str):
        return guard(svc.debrief, cid)

    @app.post("/api/campaigns/{cid}/skip")
    def skip(cid: str):
        return guard(svc.skip, cid)

    @app.get("/api/campaigns/{cid}/debrief")
    def last_debrief(cid: str):
        return guard(svc.last_debrief, cid) or {}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
