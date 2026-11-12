-- SORTIE warehouses: apply campaign stocks at mission start, read inventories back.
-- API used (DCS 2.8.8+): Airbase.getByName(name):getWarehouse(), Warehouse:getInventory()
-- -> { weapon = {}, liquids = {}, aircraft = {} } (empty tables for unlimited categories),
-- Warehouse:setItem(itemName, count), Warehouse:getItemCount(itemName),
-- Warehouse:getLiquidAmount(liquidType) with 0 jet fuel, 1 avgas, 2 MW50, 3 diesel.
SORTIE.warehouse = { bases = {}, known = {}, catalog = {} }
local W = SORTIE.warehouse

-- Verified in DCS 2.9 (first flown mission): with limited munitions and no weapon rows in the
-- mission file the warehouse is EMPTY, getInventory() lists nothing, and aircraft spawn with
-- every store that has no stock removed (fuel tanks, pods, some missiles). Unit.getAmmo() type
-- names are also not always warehouse item names ("AIM_9X" vs "weapons.missiles.AIM_9X").
-- So limited munitions is experimental: every item name we can find gets stock.
local PREFIXES = { 'weapons.missiles.', 'weapons.bombs.', 'weapons.nurs.', 'weapons.droptanks.',
                   'weapons.containers.', 'weapons.adapters.', 'weapons.gunmounts.', 'weapons.shells.' }

function W.variants(item)
  if string.find(item, '%.') then return { item } end
  local out = { item }
  for _, p in ipairs(PREFIXES) do out[#out + 1] = p .. item end
  return out
end

-- Collect every item name DCS will tell us about. Warehouse.getResourceMap is listed in the
-- scripting reference without a description, so its shape is probed defensively and reported.
function W.build_catalog()
  local found, shape = 0, 'unavailable'
  local ok, map = pcall(function() return Warehouse.getResourceMap() end)
  if ok and type(map) == 'table' then
    shape = 'table'
    local function walk(t, depth)
      for k, v in pairs(t) do
        if type(k) == 'string' and string.find(k, '%.') then
          W.catalog[k] = (type(v) == 'table') and v or true
          found = found + 1
        elseif type(v) == 'string' and string.find(v, '%.') then
          W.catalog[v] = true
          found = found + 1
        elseif type(v) == 'table' and depth < 3 then
          walk(v, depth + 1)
        end
      end
    end
    walk(map, 0)
  elseif ok then
    shape = type(map)
  end
  local sample, n = {}, 0
  for k, _ in pairs(W.catalog) do
    if n < 12 then sample[#sample + 1] = k; n = n + 1 end
  end
  SORTIE.emit('warehouse_debug', { resource_map = shape, items = found, sample = sample })
end

local function liquids(wh)
  local out = {}
  for i = 0, 3 do
    local ok, amount = pcall(wh.getLiquidAmount, wh, i)
    if ok and amount then out[tostring(i)] = amount end
  end
  return out
end

local function inventory(wh)
  local ok, inv = pcall(wh.getInventory, wh)
  if ok and type(inv) == 'table' then return inv end
  return { weapon = {}, liquids = {}, aircraft = {} }
end

function W.init()
  for key, cfg in pairs(SORTIE.cfg.warehouses or {}) do
    local ok, ab = pcall(Airbase.getByName, key)
    local wh = nil
    if ok and ab then
      local okw, w = pcall(ab.getWarehouse, ab)
      if okw then wh = w end
    end
    if wh then
      local base = { key = key, id = cfg.id, wh = wh, cfg = cfg, start = liquids(wh) }
      W.bases[#W.bases + 1] = base
      if cfg.limit_munitions then
        for item, _ in pairs(W.catalog) do       -- everything DCS knows about gets the generic stock
          pcall(wh.setItem, wh, item, (cfg.weapons and cfg.weapons[item]) or cfg.default_stock or 0)
          W.known[item] = true
        end
        local inv = inventory(wh)
        -- every weapon the warehouse lists: campaign count if tracked, generic stock otherwise
        for item, _ in pairs(inv.weapon or {}) do
          local n = cfg.weapons and cfg.weapons[item]
          pcall(wh.setItem, wh, item, n or cfg.default_stock or 0)
          W.known[item] = true
        end
        for item, n in pairs(cfg.weapons or {}) do
          pcall(wh.setItem, wh, item, n)
          W.known[item] = true
        end
      end
      if cfg.limit_aircraft then
        for ty, n in pairs(cfg.aircraft or {}) do pcall(wh.setItem, wh, ty, n) end
      end
    else
      SORTIE.log('no warehouse for airbase ' .. tostring(key))
    end
  end
  -- aircraft already on the map were born before this script ran: learn their weapons now
  for _, side in ipairs({ coalition.side.RED, coalition.side.BLUE }) do
    for _, cat in ipairs({ Group.Category.AIRPLANE, Group.Category.HELICOPTER }) do
      local ok, groups = pcall(coalition.getGroups, side, cat)
      if ok and groups then
        for _, g in ipairs(groups) do
          local oku, units = pcall(g.getUnits, g)
          if oku and units then
            for _, u in ipairs(units) do
              local a = {}
              pcall(function()
                for _, e in ipairs(u:getAmmo() or {}) do
                  if e.desc and e.desc.typeName then a[e.desc.typeName] = e.count end
                end
              end)
              W.seen(a)
            end
          end
        end
      end
    end
  end
  W.report('start')
end

-- A weapon item name the campaign has never tracked: give every limited base its generic stock.
function W.seen(ammo)
  for raw, _ in pairs(ammo or {}) do
    for _, item in ipairs(W.variants(raw)) do
      if not W.known[item] then
        W.known[item] = true
        for _, base in ipairs(W.bases) do
          if base.cfg.limit_munitions then
            local ok, n = pcall(base.wh.getItemCount, base.wh, item)
            if ok and (n or 0) == 0 then pcall(base.wh.setItem, base.wh, item, base.cfg.default_stock or 0) end
          end
        end
      end
    end
  end
end

function W.report(phase)
  for _, base in ipairs(W.bases) do
    local inv = inventory(base.wh)
    local weapons = {}
    for item, _ in pairs(W.known) do
      local ok, n = pcall(base.wh.getItemCount, base.wh, item)
      if ok and n then weapons[item] = n end
    end
    for item, n in pairs(inv.weapon or {}) do weapons[item] = n end
    SORTIE.emit('warehouse', {
      phase = phase, base = base.id, key = base.key,
      liquids_start = base.start, liquids = liquids(base.wh),
      weapons = weapons, aircraft = inv.aircraft or {},
    })
  end
end

SORTIE.safe('warehouse.catalog', W.build_catalog)
SORTIE.safe('warehouse.init', W.init)
SORTIE.every(300, 'warehouse.report', function() W.report('periodic') end)
