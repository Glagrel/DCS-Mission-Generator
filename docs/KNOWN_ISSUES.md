# SORTIE — Known issues and limitations

**Nothing in this project has been run inside DCS.** Items marked *unverified* are implemented
and tested against fixtures/mocks only; see TEST_IN_DCS.md for the checks.

## Blocked by an external dependency

1. **No Marianas WWII terrain in pydcs 1.0.0.** Operation Forager builds on the modern
   `MarianaIslands` map (modern runways and buildings). Change `terrain:` handling in
   `sortie/terrain.py` when pydcs adds it; the template already asks for `MarianaIslandsWWII`.
2. **No Japanese aircraft or warships in DCS.** Japan flies Bf 109 K-4 / Fw 190 A-8 / Ju 88 A-4
   stand-ins and uses generic cargo ships. The US has no WWII escorts either (Essex, LSTs and
   transports only).
3. **Piper TTS** is not an MSRS provider. Selecting it falls back to Windows TTS.
4. **Per-weapon rows in the .miz warehouses file** need `wsType` codes that pydcs does not
   ship. Weapon stocks are applied by Lua at mission start instead (`Warehouse.setItem`).

## Implemented, awaiting DCS verification

5. **Warehouses.** Assumed: `InitFuel` is in tonnes; a limited-munitions warehouse with an
   empty weapons table lists items via `getInventory()` so the script can set them; aircraft
   spawn with their loadout even when stock is applied a moment later by script. If
   `getInventory()` returns nothing, only weapons seen on spawned aircraft get stock and
   everything else is zero — set `logistics.limit_munitions: false` to work around it.
6. **Limited airframes in warehouses** are off by default (`logistics.limit_aircraft`).
7. **Carrier operations.** Carrier starts use pydcs `flight_group_from_unit`; deck spawning,
   recovery waypoints and the carrier's own warehouse are unverified. No TACAN/ICLS is set.
8. **AI tasking.** Strike flights get `AttackGroup`/`Bombing`/`BombingRunway` at the IP,
   escorts an `EscortTaskAction` on the package lead, CAP an orbit. Timing is best-effort:
   package flights take off when the mission starts rather than holding for a push time, so
   they may reach the target before you.
9. **Proximity manager.** Ground groups far from your route are late-activated and switched
   on within `spawn_km`; finished AI flights far away are removed and flagged so they are
   never counted as losses. Whether DCS emits `dead` events for `Group.destroy()` is unverified
   (handled either way).
10. **Supply nodes** are clusters of static objects at the node's coordinates, not the map's
    own buildings/bridges. A "bridge" node is represented by statics next to the bridge.
    Coordinates were set by hand from memory of the maps; some may sit in water or on slopes.
11. **Ground units** are placed about 3 km either side of a straight front line through the
    axis and do not move or fight their way forward in DCS; the front moves between sorties.
12. **ATC layer.** GCI "sees" every airborne hostile within 185 km (no radar modelling);
    bearings are true, not magnetic; runway in use and QNH are not computed (placeholders in
    tower calls). MOOSE `AWACS`, `AIRBOSS`, `CSAR` and `AI_A2A_DISPATCHER` are not used
    (DECISIONS 20). MSRS/SRS voice is untested.
13. **Event log without desanitize** goes to `dcs.log`; it can be imported after the mission
    but there is no live feed.

## Partial / simplified by design

14. **Abstract air war** is a seeded probability model on coarse ratings derived from era and
    speed, not a performance model. Numbers in `sim/airwar.py` and `config/defaults.yaml` need
    tuning from play.
15. **Fog of war** is not modelled: all enemy positions and SAMs are shown on the map.
16. **Runway damage** is not reported by DCS events; airbase strikes flown in DCS are credited
    from weapons released and aircraft surviving.
17. **Weather** uses simple cloud base/density/wind fields, not the DCS cloud presets.
18. **Co-op career** tracks only the pilot in slot 1 of the player flight.
19. **Loadouts** are the first stock DCS payload tagged for the task, not optimised for the
    target; with no DCS install found aircraft are generated clean.
20. **Aircraft callsigns** shown in the briefing are the ones pydcs assigned in the mission
    after generation; before generation the ATO page shows the squadron's planning callsign.
21. **Cold War template** uses Tornado GR4 for the RAF Tornado GR1 and F-4E for the Luftwaffe
    F-4F; the Gulf template uses the DCS country Iran for the fictional opponent.
22. **Map tiles and Leaflet** load from the internet (OpenStreetMap, unpkg).

## Added with the co-op / timeline rework

23. **Co-op guest flights:** the AI lead of a guest's flight is not held for the human and may
    take off first. Guests can only join flights that are still on the ground at mission start.
24. **Plane guard under MOOSE** is respawned by RESCUEHELO under a new group name; if it is shot
    down the squadron's airframe count is not reduced. Without MOOSE it does not follow the ship.
25. **Shared stands:** when a ramp is full a later flight appears on a stand vacated earlier, or
    lines up on the runway at take-off time. On very small airfields this can still fall back to
    entering airborne over the base (a warning is shown).
26. **AI departure timing** uses a fixed taxi allowance (`mission.taxi_minutes`); real taxi times
    vary, so TOTs are approximate.
27. **Kneeboard pages** are per aircraft type: two flights of the same type with human seats see
    each other's flight cards (labelled by callsign).
28. **Dedicated server on another PC:** copy the event file back or point *Server Saved Games*
    at a share; the mission falls back to that server's own Saved Games folder.
