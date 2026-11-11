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
