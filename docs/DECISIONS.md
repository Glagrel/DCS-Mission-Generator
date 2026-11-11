# SORTIE — Decisions and flags

Entries are numbered; **FLAG** marks things that need in-sim verification or later tuning.

1. **pydcs package name.** `pip install -U dcs` installs an unrelated Rackspace package
   ("Dynamic Chef Solo", v0.1.1). The DCS mission library is published as **`pydcs`**
   (import name `dcs`). Setup installs `pydcs` (1.0.0 at time of writing) and removes `dcs`.
2. **Terrains in pydcs 1.0.0:** afghanistan, caucasus, falklands, germany (GermanyCW),
   kola, marianaislands, nevada, normandy, persiangulf, sinai, syria, thechannel.
   **The Marianas WWII map is missing.** Operation Forager is built on the modern
   `MarianaIslands` terrain (same islands, same coordinates; modern airfields/buildings
   visible). **FLAG** — when pydcs adds `MarianaIslandsWWII`, change `terrain:` in
   `data/theaters/forager_1944.yaml`.
3. **No Japanese aircraft or warships exist in DCS/pydcs.** Japan flies stand-ins under the
   `Japan` country: Bf-109K-4 (fighter), FW-190A8 (fighter-bomber), Ju-88A4 (bomber).
   Japanese shipping uses generic cargo ships. Japanese ground units use the real WWII
   Asset Pack types pydcs lists (Type 89 I-Go, Type 98 Ke-Ni, Type 88 75 mm AA, …). **FLAG**
4. **State storage:** pydantic documents stored as JSON rows in SQLite (one table of
   entities keyed by campaign/kind/id plus a history table) rather than a fully normalised
   schema. Simple, migration-free, and still queryable with SQLite JSON functions.
5. **Warehouse weapons.** pydcs has no `wsType` table, which the `.miz` `warehouses` file
   needs for per-weapon rows. So: the .miz carries coalition, limited-flags, fuel (tons)
   and aircraft counts per airbase; **per-weapon stock is applied at mission start by Lua**
   through the documented `Warehouse.setItem(itemName, count)` API from a table generated
   from campaign state, and read back with `getInventory()` / `getLiquidAmount()`.
   Weapon item names the campaign has never seen are discovered at runtime (`Unit.getAmmo`
   on birth, inventory dump) and given the base's `munition_level × default_stock`; they are
   reported back so the campaign tracks them from then on. `data/weapon_seed.yaml` holds a
   small best-effort seed list of item names. **FLAG** — verify in DCS.
6. **Aircraft warehouse format** assumed `aircrafts = {planes={[type]={initialAmount=n}},
   helicopters={…}}`. **FLAG**
7. **Turn = one ATO cycle** of 6 campaign hours by default; one player sortie per turn.
8. **Group naming contract** `S|kind|entity|n` links DCS objects back to campaign entities.
9. **Era data.** pydcs has no in-service years. `data/unit_eras.yaml` lists introduction
   years for the types used; unknown types are treated as "modern" (2000) so they are
   excluded from older eras by default.
10. **Owned modules default** = every pydcs `flyable` aircraft/helicopter, filtered by era in
    the wizard.
11. **DCS path detection:** Saved Games = candidate folder with newest `Logs\dcs.log`;
    install = registry `HKCU\Software\Eagle Dynamics\*` `Path` values validated by
    `bin\DCS.exe`/`bin-mt\DCS.exe`, then common paths on all drives; overridable in settings.
12. **MOOSE** is downloaded by `tools/fetch_moose.py` from the official
    `FlightControl-Master/MOOSE_INCLUDE` repo (`Moose_Include_Static/Moose_.lua`) into
    `vendor/moose/`. Offline: place `Moose_.lua` there by hand. Missions still build without
    it (SORTIE's own Lua does not depend on MOOSE; only the ATC layer does).
13. **Revised brief (project boundaries).** The coding agent never writes outside the project
    folder and never runs the integration scripts. The *application*, when the user clicks
    "Generate next mission", writes the `.miz` and runtime folder under
    `<SavedGames>\Missions\SORTIE\` (that is the product's function and is configurable via
    `output_dir`). All tests use temp directories.
14. **Schema migrations:** ordered `MIGRATIONS` list in `sortie/db.py`, version in
    `PRAGMA user_version`. Entity documents are pydantic models with defaults, so adding
    fields needs no migration.
15. **Gulf template:** the fictional "Farsian Republic" uses the DCS country `Iran`.
    Cold War template uses Tornado GR4 as the RAF Tornado GR1 stand-in and F-4E for the
    Luftwaffe F-4F (pydcs has neither).
16. **Fronts are an axis** (blue rear anchor → red rear anchor) with a position 0..1; ground
    formations are placed ~3 km either side of the line at mission-build time. Simple, but it
    gives front movement, CAS targets and base capture (an airbase overrun by the line flips).
