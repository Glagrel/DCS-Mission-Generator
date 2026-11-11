-- SORTIE warehouses: apply campaign stocks at mission start, read inventories back.
-- API used (DCS 2.8.8+): Airbase.getByName(name):getWarehouse(), Warehouse:getInventory()
-- -> { weapon = {}, liquids = {}, aircraft = {} } (empty tables for unlimited categories),
-- Warehouse:setItem(itemName, count), Warehouse:getItemCount(itemName),
-- Warehouse:getLiquidAmount(liquidType) with 0 jet fuel, 1 avgas, 2 MW50, 3 diesel.
SORTIE.warehouse = { bases = {}, known = {} }
local W = SORTIE.warehouse

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
  for item, _ in pairs(ammo or {}) do
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

SORTIE.safe('warehouse.init', W.init)
SORTIE.every(120, 'warehouse.report', function() W.report('periodic') end)
