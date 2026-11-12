# SORTIE — tests that need DCS

None of these has been run. Fill in **Actual** and **P/F** as you go. Unless stated otherwise:

* **Setup A (default):** `tools\setup.ps1` done, `tools\install_desanitize.ps1` applied, GUI
  running, a Persian Gulf career in an aircraft you own, Settings → Player slots = 1, ATC off,
  "Generate Next Mission" pressed, mission `SORTIE_gulf_crisis_T001.miz` opened from
  *Mission → My Missions → SORTIE*.
* Watch `<Saved Games>\Logs\dcs.log` for lines starting `SORTIE` and for Lua errors.
* When a test fails, note the dcs.log lines around the failure.

## 1. Loading

| # | Test | Theater / aircraft / setup | Steps | Expected | Actual | P/F |
|---|---|---|---|---|---|---|
| 1.1 | Mission loads | Gulf / any owned / A | Open the mission | Loads without error dialog; briefing shows TASKING, WHY YOU, ROUTE | | |
| 1.2 | Mission loads (Cold War) | Germany CW / F-15C or other owned / A with Cold War career | Open the mission | Loads; units of 1985 only | | |
| 1.3 | Mission loads (Marianas) | Marianas (modern map) / F4U-1D / A with Forager career | Open the mission | Loads on the modern Marianas map; GUI showed the terrain warning | | |
| 1.4 | MOOSE loads | Gulf / A | Start mission, search dcs.log | Line `*** MOOSE GITHUB Commit Hash ID` appears before `SORTIE: scripts loaded`; no script error | | |
| 1.5 | Mission-start trigger | Gulf / A | Start mission, search dcs.log | `SORTIE: writing events to ...events.jsonl` and `SORTIE: scripts loaded (mode file)` | | |
| 1.6 | Start without MOOSE | Gulf / rename `vendor\moose\Moose_.lua`, regenerate | Start mission | Mission and SORTIE scripts still load | | |

## 2. Slots

| # | Test | Theater / aircraft / setup | Steps | Expected | Actual | P/F |
|---|---|---|---|---|---|---|
| 2.1 | SP slot | Gulf / A | Fly | You are in slot 1 of your flight, cold on the ramp at the briefed base, AI wingmen beside you | | |
| 2.2 | Co-op client slots | Gulf / Player slots = 2, regenerate, host as server | Open slot list | Two client slots in the player flight, remaining aircraft AI | | |
| 2.3 | Co-op second player | as 2.2 with a second PC | Both join | Both spawn; events show both player names | | |
| 2.4 | Carrier start | Forager F4U-1D or Gulf FA-18C career / A | Fly | Spawn on the carrier deck; deck is usable; can launch | | |
| 2.5 | Loadout | Gulf / A | Check rearm panel | Aircraft carries the loadout listed in the briefing | | |
| 2.6 | Radio | Gulf / A | Check radio preset 1 | Tuned to the briefed flight frequency | | |

## 3. AI and world

| # | Test | Theater / aircraft / setup | Steps | Expected | Actual | P/F |
|---|---|---|---|---|---|---|
| 3.1 | Package AI takes off | Gulf / A | Watch F2 view | Other flights of your package start and take off | | |
| 3.2 | Airborne AI spawns on time | Gulf / A | F10 map over time | Other flights appear at their start times and fly their routes | | |
| 3.3 | AI strike tasks | Gulf / STRIKE or SEAD package | Follow the lead | Strikers attack the briefed target; escorts stay with them | | |
| 3.4 | CAP orbits | Gulf / A | F10 map | CAP flights race-track at their stations | | |
| 3.5 | AWACS / tanker | Gulf / A | Comms menu | AWACS and tanker on station, contactable on briefed frequencies | | |
| 3.6 | Ground groups | Gulf / CAS tasking | Fly to the front | Formations on both sides of the front, correct coalitions | | |
| 3.7 | SAM sites | Gulf / A | Fly near a briefed SAM | Site is alive, radars on, engages | | |
| 3.8 | Naval groups | Gulf / A | F10 map | Carrier group and enemy flotilla present and moving | | |
| 3.9 | Supply-node statics | Gulf / STRIKE on a depot | Overfly target | Cluster of buildings at the target; damaged nodes show some destroyed | | |
| 3.10 | Convoys | Gulf / INTERDICTION | Find the route | Truck column on the road, moving | | |
| 3.11 | Statics placement | all three theaters | Look at each node you pass | Objects stand on land, not in water or on steep slopes (note bad ones) | | |
| 3.12 | Performance | Gulf / Standard profile | Watch FPS | Playable; note FPS and whether to tune `config\defaults.yaml` | | |

## 4. Warehouses

| # | Test | Theater / aircraft / setup | Steps | Expected | Actual | P/F |
|---|---|---|---|---|---|---|
| 4.1 | Limited fuel | Gulf / A | Rearm/refuel panel at home base; F10 airbase resources | Fuel is limited and matches the Logistics page (tonnes) | | |
| 4.2 | Low fuel base | Edit nothing; fly from a base the GUI shows nearly empty | Try to refuel fully | Refuel is limited by stock | | |
| 4.3 | Limited weapons | Gulf / A | Rearm panel | Weapons limited; counts ≈ `default_weapon_stock × munition level` on first sortie | | |
| 4.4 | Spawn loadout with limited stock | Gulf / A | Spawn | Aircraft still spawns armed | | |
| 4.5 | Warehouse start report | Gulf / A | Open events.jsonl | A `warehouse` line with `phase":"start"`, non-empty `liquids_start` and `weapons` | | |
| 4.6 | Readback | Gulf / A | Rearm, refuel, fly, end mission, debrief | Debrief "Warehouse readback" lists the base; Logistics shows per-weapon counts and lower fuel | | |
| 4.7 | Stocks persist | after 4.6 | Generate and fly the next mission | Rearm panel shows the reduced counts | | |
| 4.8 | Carrier warehouse | carrier career | Rearm on deck | Limited fuel/weapons apply on the carrier | | |

## 5. Events and watcher

| # | Test | Theater / aircraft / setup | Steps | Expected | Actual | P/F |
|---|---|---|---|---|---|---|
| 5.1 | File permissions | Gulf / A | Start mission | `<Saved Games>\Missions\SORTIE\runtime\events.jsonl` is created | | |
| 5.2 | Flushing | Gulf / A | Tail the file while flying | Lines appear immediately, one JSON object per line | | |
| 5.3 | Live feed | Gulf / A, GUI on Live Mission | Fly | Take-off, kills, losses appear within ~2 s; situation table updates every 30 s | | |
| 5.4 | Take-off / landing | Gulf / A | Take off, land | `takeoff` and `land` events with your name and airbase | | |
| 5.5 | Kill | Gulf / A | Destroy a ground unit and an aircraft | `kill` events with target; debrief credits you | | |
| 5.6 | Crash | Gulf / A | Crash an aircraft | `crash` event; debrief shows aircraft lost | | |
| 5.7 | Ejection | Gulf / A | Eject | `eject` event; debrief shows ejected; pilot status sensible | | |
| 5.8 | Pilot death | Gulf / A | Die | Career ends (KIA) and no further mission can be generated | | |
| 5.9 | Structure destruction | Gulf / STRIKE on a depot | Destroy statics | Debrief: "n of m structures destroyed"; node health drops on Logistics | | |
| 5.10 | SAM destruction | Gulf / SEAD | Destroy radar/launchers | SAM health drops; ring fades/shrinks on the next map | | |
| 5.11 | Base capture | any | Capture an airfield with ground units (mission editor edit if needed) | `base_captured` event; airbase changes side after debrief | | |
| 5.12 | Mission end | Gulf / A | Quit mission normally | `mission_end` line and a final `warehouse` line with `phase":"end"` | | |
| 5.13 | Mission restart | Gulf / A | Restart mission (LShift+R) | File restarts; GUI feed resets; only the last run is debriefed | | |
| 5.14 | Sanitised fallback | Run `install_desanitize.ps1 -Undo`, fly | Search dcs.log | `SORTIE_EVT {...}` lines; `python -m sortie import-log` then debrief works | | |
| 5.15 | Script robustness | Gulf / A | Fly 60+ min | No `SORTIE error` lines in dcs.log | | |

## 6. Proximity spawn / despawn

| # | Test | Theater / aircraft / setup | Steps | Expected | Actual | P/F |
|---|---|---|---|---|---|---|
| 6.1 | Late ground groups | Gulf / Light profile | Fly toward a distant formation | Group appears when within spawn distance; `spawn` event written | | |
| 6.2 | Despawn finished flights | Gulf / A | Stay far from a landed/finished AI flight | Group removed; `despawn` event lists its units | | |
| 6.3 | Despawn is not a loss | after 6.2 | Debrief | Squadron losses do not include despawned aircraft | | |
| 6.4 | Player group untouched | Gulf / A | Fly a long sortie | Your flight is never removed | | |

## 7. ATC / GCI / voice (enable in Settings, regenerate)

| # | Test | Theater / aircraft / setup | Steps | Expected | Actual | P/F |
|---|---|---|---|---|---|---|
| 7.1 | Off by default | Gulf / A | Fly | No controller messages, no "SORTIE Control" F10 menu | | |
| 7.2 | On-screen comms | Gulf / ATC on, voice off | Start, taxi, take off | Start-up/taxi, departure, check-in texts shown to your group | | |
| 7.3 | F10 menu | as 7.2 | F10 → SORTIE Control | Picture, Bogey dope, Declare, Vector to home, Vector to tanker respond | | |
| 7.4 | Picture / threat | as 7.2 | Fly toward enemy fighters | Periodic picture; threat call inside 25 nm; "merged" close in; bearings/ranges plausible | | |
| 7.5 | Approach / landing | as 7.2 | Return and land | Inbound, cleared-to-land, welcome-home messages | | |
| 7.6 | Soviet procedures | Cold War, red side career, ATC on | Fly | Metric ranges/heights, Soviet-style phrasing, no AWACS | | |
| 7.7 | WWII procedures | Forager, ATC on | Fly | Only simple vectors ("angels", "bandits"); no bullseye, declare, tanker or CSAR | | |
| 7.8 | SRS voice (Windows) | Gulf / ATC on, voice windows, SRS running | Tune briefed frequency | Messages are spoken and still shown as text | | |
| 7.9 | SRS voice (Google) | as 7.8 with Google credentials | Tune | Spoken with Google voice | | |
| 7.10 | Voice without MOOSE/SRS | voice windows, SRS closed | Fly | No errors; text still shown | | |
| 7.11 | FLIGHTCONTROL tower | `atc.use_flightcontrol: true`, voice on | Taxi/take off | MOOSE tower handles your flight; no duplicate SORTIE tower texts | | |
| 7.12 | CSAR notice | Gulf / ATC on | Eject | Controller acknowledges; `csar` event written | | |

## 7b. Timeline, co-op guests, carrier support, kneeboard

| # | Test | Theater / aircraft / setup | Steps | Expected | Actual | P/F |
|---|---|---|---|---|---|---|
| 9.1 | Mission clock | Gulf / A | Start mission | Clock reads the "Mission starts" time from the briefing, about 10 min before your take-off time | | |
| 9.2 | Parked AI starts on time | Gulf / A | Watch a parked AI flight (F10/F2) | Cold and still until about 5 min before its take-off time, then starts, taxis, takes off | | |
| 9.3 | Airborne at start | Gulf / A | F10 at mission start | AWACS, tanker and flights already en route are in the air from second zero; nothing appears in mid-air later | | |
| 9.4 | Everyone lands | Gulf / A | Follow a returning flight | It lands and parks; only then is it removed (if far from players) | | |
| 9.5 | Shared stand / runway start | a small base with several flights | Watch the ramp | Later flight appears on a vacated stand or on the runway at take-off time; no collisions | | |
| 9.6 | AWACS/tanker stay on station | Gulf / A | Fly a long sortie | Both orbit for the whole mission, then go home | | |
| 9.7 | Earlier this cycle | Gulf / late TOT | Read the briefing | Results of packages flown before your launch are listed and visible in the mission (e.g. damaged SAM) | | |
| 9.8 | Guest slots | Gulf / extra pilots = 2, host | Slot list | Client slots in other flights, in the listed aircraft, cold on the ramp | | |
| 9.9 | Guest accounting | as 9.8, guest flies, kills, loses the jet | Debrief | Pilots table shows the guest; that squadron lost an airframe; kills credited | | |
| 9.10 | Unused guest seat | as 9.8, nobody takes one seat | Debrief | No loss, no fuel or weapons charged for that seat | | |
| 9.11 | Messages to all humans | co-op with ATC on | Fly | Controller texts reach every human group | | |
| 9.12 | Campaign link notice | Gulf / A | 10 s after start | "SORTIE: campaign link active" (or the desanitize hint) on screen | | |
| 9.13 | Dedicated server | save to server on | Start the server with the copied mission | Mission loads; events appear in the GUI live feed | | |
| 9.14 | Plane guard | carrier career | Look off the starboard side | SH-60B close aboard at low altitude, staying with the ship | | |
| 9.15 | Recovery tanker | carrier career | Look overhead / comms | S-3B orbiting the carrier at about 6,000 ft, usable as tanker | | |
| 9.16 | Kneeboard | any | Open the kneeboard in the cockpit | SORTIE flight card and support pages are present and readable | | |
| 9.17 | Units | Settings → metric, regenerate | Briefing and kneeboard | Altitudes in m, speeds in km/h, distances in km | | |

## 8. Campaign continuity

| # | Test | Theater / aircraft / setup | Steps | Expected | Actual | P/F |
|---|---|---|---|---|---|---|
| 8.1 | Three-sortie campaign | Gulf / A | Fly, debrief, generate ×3 | Each mission reflects the previous: destroyed SAMs/nodes stay damaged, fronts move, stocks change | | |
| 8.2 | Assignment follows the war | Gulf / A | Let the enemy bomb your base (or lose fighters) | Later taskings shift toward CAP/intercept with matching reasons | | |
| 8.3 | Reassignment | Lose all squadron aircraft | Debrief | Transfer to another squadron flying a module you own, with a reason | | |
