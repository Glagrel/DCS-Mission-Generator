# SORTIE — Progress log

## Phase 0 — setup and research
- Environment: Python 3.14.6, 31 GB RAM (→ Standard profile), Saved Games `DCS.openbeta`,
  install `E:\Program Files\Eagle Dynamics\DCS World OpenBeta` (DCS 2.9.31), internet OK.
- venv `.venv`; installed pydcs 1.0.0, pydantic, fastapi, uvicorn, psutil, pytest, httpx, pyyaml.
- Verified pydcs by prototype: client flight from airport, carrier flight, in-flight AI
  group with late activation, vehicle/ship/static groups, MISSION START DoScriptFile
  trigger, airport warehouse fields, save + reload. See DECISIONS 1-6.
- Wrote SPEC.md, PLAN.md, DECISIONS.md.
- Scaffold: `sortie/paths.py`, `sortie/config.py`, `config/defaults.yaml`, `tools/setup.ps1`,
  `tools/run.ps1`, `tools/fetch_moose.py` (MOOSE downloaded, 4.4 MB). 6 tests pass.

## Phase 1 — data model + SQLite state
- `sortie/models.py` (entities), `models_ato.py` (ATO, results), `db.py` (document store +
  history), `state.py` (load/mutate/save whole campaign, seeded RNG, clock), `geo.py`.
- 9 tests pass.

## Phase 2 — theater templates
- `sortie/units.py` (pydcs lookup, era filter, ratings), `terrain.py` (terrain abstraction with
  documented Marianas fallback), `theater.py` (schema + cross-validation), `campaign.py`
  (career creation, owned-module gate), `debrief/career.py` (ranks/awards).
- Data: `unit_eras.yaml`, `sam_templates.yaml`, three templates. All validate against pydcs.
- Revised brief received mid-phase: added DB migrations (`PRAGMA user_version`), `events` and
  `cursors` tables, `sortie/logs.py` (JSON-lines logging), `pyproject.toml`.
- 27 tests pass.

## Phase 3 — between-sortie war simulator
- `sim/readiness.py` (grounding rules, sortie costs), `sim/supply.py` (production → routes →
  bases/troops, interdiction decay, carrier UNREP), `sim/production.py` (replacements by
  deficit priority, repairs), `sim/airwar.py` (seeded probabilistic resolution: air
  opposition, SAM threat on route, target effects), `sim/ground.py` (front movement,
  attrition, capture of bases/nodes/SAMs, victory), `sim/turn.py` (pipeline + clock, weather
  drift, naval movement). 42 tests pass, all seeded/deterministic.

## Phase 4 — ATO generator + player assignment
- `ato/needs.py` (transparent scoring with a reason per need), `ato/planner.py` (allocation
  with squadron pool, range check, diminishing returns per mission type, attached SEAD and
  escort flights, support info), `ato/route.py` (waypoints, SAM-aware ingress choice, ETAs
  anchored on TOT), `ato/radio.py` (bands per doctrine/era, callsigns, TACAN), `ato/assign.py`
  (player flight chosen by the ATO, forced tasking, stand-down reasons, owned-module gate),
  `mission/loadouts.py` (payload pick via pydcs payload files; empty when DCS is absent).
- 62 tests pass.

## Phase 5 / 6 — mission builder and in-mission Lua (IN PROGRESS, session stopped here)
Done:
- `mission/budget.py`, `forces.py`, `flights.py`, `warehouses.py`, `scripts.py`, `briefing.py`,
  `builder.py`; `atc/procedures.py` + `atc/luacfg.py` (config only). Trial builds of all three
  theaters produce .miz files that pydcs reloads; real DCS payloads load when the install is found.
- Lua: `sortie_json.lua`, `sortie_core.lua`, `sortie_events.lua`, `sortie_warehouse.lua`,
  `sortie_spawn.lua`, tested under real Lua 5.1 (lupa) with a mocked DCS API (12 tests).
- Warehouse API verified on the Hoggit wiki (getInventory/setItem/getLiquidAmount, 2.8.8+).
Not done yet:
- pytest tests for the mission builder itself (only ad-hoc trial builds were run).
- `sortie/lua/sortie_atc.lua` does not exist: building with `atc_enabled=true` fails.
- Phase 7 (ingest, watcher, reassign), Phase 8 (GUI, `python -m sortie` entry point used by
  tools/setup.ps1 and run.ps1), Phase 9, Phase 10 (README, TEST_IN_DCS.md, KNOWN_ISSUES.md,
  install_desanitize.ps1, e2e test). PLAN.md boxes for 5-10 are still unticked.

## Phase 5 / 6 — completed
- `tests/test_mission.py` (16 tests): each theater builds and reloads in pydcs, SP `Player`
  slot vs co-op `Client` slots, carrier start, profiles scale content, warehouses, degraded
  spawns, briefing, error reporting, .miz verification. Fixed: targets of simulated packages
  are now always inside the ground budget. 90 tests pass.
- Lua needs in-sim verification; nothing here has been run in DCS.

## Phase 7 — after-action ingestion, career, reassignment
- `runtime/watcher.py` (tail with durable cursor, partial lines, restarts, duplicates,
  malformed lines, dcs.log fallback), `runtime/aar.py` (facts + timeline), `debrief/ingest.py`
  (losses, entity damage, captures, warehouse readback, player result), `debrief/reassign.py`
  (owned-module-safe transfers with reasons), `service.py` (plan → generate → live → debrief →
  next turn; skip), `runtime/simulate.py` (synthetic events in the Lua's format).
- 103 tests pass.

## Phase 8 — web GUI
- `web/app.py` (FastAPI: status, settings, modules, theaters, campaigns, overview, map, ATO,
  briefing, roster, career, logistics, history, generate, live, debrief, skip), `web/views.py`,
  static SPA (`index.html`, `style.css`, `app.js`, `pages.js`, `mission.js`) with Leaflet map.
- `python -m sortie gui|doctor|simulate` (`sortie/__main__.py`).
- Checked in a browser against a temp database: wizard, mission generation (path shown),
  ATO/briefing, map layers, roster, pilot, logistics, live, settings all render with no JS errors.
- Bug found and fixed: parallel GUI requests shared one SQLite connection (now serialised;
  regression test added).

## Phase 9 — ATC / GCI / SRS layer (feature flag, default off)
- `atc/procedures.py` (NATO, Soviet-style, WW2 phrase sets + formatting), `atc/luacfg.py`,
  `lua/sortie_atc.lua` (tower sequence, check-in, picture, bogey dope, declare, threat, merged,
  vectors to home/tanker, CSAR notice, F10 menu; text always, MSRS voice when MOOSE is loaded).
- MOOSE signatures verified against the vendored `Moose_.lua` (commit 130d358f, 2026-02-06):
  `MSRS:New(Path,Frequency,Modulation,Backend)`, `SetPort/SetCoalition/SetCulture/SetProvider/
  SetGoogle/PlayText`, `MSRS.Provider.{WINDOWS,GOOGLE,AZURE,AMAZON}`,
  `FLIGHTCONTROL:New(AirbaseName,Frequency,Modulation,PathToSRS,Port,GoogleKey)`.
- Python and Lua produce identical phrases (parity tests). 127 tests pass.

## Phase 10 — documentation and end-to-end verification
- `tools/install_desanitize.ps1` (backup, apply, `-Undo`, `-DryRun`, `-Force`, path checks);
  tested by pytest against a fake install in a temp folder only. Never run on the real install.
- `tools/fetch_moose.py` now records `vendor/moose/SOURCE.txt`.
- `README.md`, `docs/TEST_IN_DCS.md` (66 in-sim checks with actual/pass-fail columns),
  `docs/KNOWN_ISSUES.md`, SPEC section 13.
- `tests/test_e2e.py`: full flow for all three theaters over four cycles, restart safety,
  12-cycle abstract war. `python -m sortie doctor` verified on this machine (read-only).
- Final: 135 tests pass. No file outside the project folder was written by the agent except
  temp directories. Nothing has been run in DCS.

## Rework after first user feedback (co-op, timeline, carrier ops, kneeboard, server, units)
- Researched DCS Retribution (state-file path fallbacks and write-failure notice in its
  `dcs_retribution.lua`; start-at-player-start-up) and carrier support doctrine.
- `mission/clock.py` (T0, phases, interpolated air state), `mission/slots.py` (human seats incl.
  guests in other flights), `mission/kneeboard.py` (Pillow pages), `measure.py` (units),
  `lua/sortie_carrier.lua`; rewrote `mission/flights.py`; concurrency cap in `mission/budget.py`.
- Orbit flights now have station time (this is why AWACS/tankers were missing from missions:
  their planned window ended before the player launched and they were filtered out).
- ATO: `SAR` plane guard and recovery tanker per carrier; SH-60B squadrons in the Gulf template.
- Service: pre-launch resolution, events read from client/server/%TEMP%, server mission copy.
- GUI: co-op and server settings, units toggle, slot table, kneeboard/clock info, per-pilot debrief.
- 162 tests pass. Still nothing run in DCS.

## Second feedback round
- Root cause of "no AWACS/tanker in the mission editor": the campaign's saved ATO came from the
  older planner. Added plan versioning with automatic re-planning of unflown plans.
- Support flights on station from cycle start until the last tasking lands / next cycle.
- JOIN waypoint for multi-flight packages; hot-start option; `Stop SORTIE.bat`, restart-on-start.
- Verified on a copy of the user's campaign database: mission now contains E-3A, KC-135MPRS and
  the S-3B recovery tanker, airborne at mission start. 171 tests pass.
