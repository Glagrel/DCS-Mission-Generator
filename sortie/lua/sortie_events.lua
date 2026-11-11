-- SORTIE event logger + periodic snapshots. Uses only the native DCS scripting API.
SORTIE.events = {}
SORTIE.despawned = {}     -- unit names removed by the proximity manager (not combat losses)

local E = world.event
local names = {}
local function map(id, name) if id then names[id] = name end end
map(E.S_EVENT_SHOT, 'shot')
map(E.S_EVENT_HIT, 'hit')
map(E.S_EVENT_TAKEOFF, 'takeoff')
map(E.S_EVENT_LAND, 'land')
map(E.S_EVENT_CRASH, 'crash')
map(E.S_EVENT_EJECTION, 'eject')
map(E.S_EVENT_DEAD, 'dead')
map(E.S_EVENT_PILOT_DEAD, 'pilot_dead')
map(E.S_EVENT_BASE_CAPTURED, 'base_captured')
map(E.S_EVENT_BIRTH, 'birth')
map(E.S_EVENT_ENGINE_STARTUP, 'engine_start')
map(E.S_EVENT_REFUELING, 'refuel')
map(E.S_EVENT_PLAYER_ENTER_UNIT, 'player_enter')
map(E.S_EVENT_PLAYER_LEAVE_UNIT, 'player_leave')
map(E.S_EVENT_KILL, 'kill')
map(E.S_EVENT_UNIT_LOST, 'lost')
map(E.S_EVENT_LANDING_AFTER_EJECTION, 'pilot_landed')
map(E.S_EVENT_MISSION_END, 'mission_end')
SORTIE.events.names = names

local function ammo(unit)
  -- weapon item names carried by a unit: lets the campaign learn warehouse item names
  local out = {}
  pcall(function()
    local list = unit:getAmmo()
    if list then
      for _, a in ipairs(list) do
        if a.desc and a.desc.typeName then out[a.desc.typeName] = a.count end
      end
    end
  end)
  return out
end

function SORTIE.events.handle(event)
  local name = names[event.id]
  if not name then return end
  local d = {}
  d.i = SORTIE.ref(event.initiator)
  d.tg = SORTIE.ref(event.target)
  if event.weapon then
    pcall(function() d.w = event.weapon:getTypeName() end)
  end
  if event.weapon_name and not d.w then d.w = event.weapon_name end
  if event.place then
    pcall(function() d.place = event.place:getName() end)
    if name == 'base_captured' then pcall(function() d.c = event.place:getCoalition() end) end
  end
  if event.initiator and (name == 'eject' or name == 'crash' or name == 'land' or name == 'dead'
      or name == 'lost' or name == 'kill') then
    d.pos = SORTIE.latlon(event.initiator)
  end
  if name == 'birth' and d.i and d.i.cat == Object.Category.UNIT then
    local a = ammo(event.initiator)
    if next(a) then d.ammo = a end
    if SORTIE.warehouse and SORTIE.warehouse.seen then SORTIE.safe('wh.seen', SORTIE.warehouse.seen, a) end
  end
  -- units destroyed by the proximity manager are flagged so Python never counts them as losses
  if d.i and d.i.n and SORTIE.despawned[d.i.n] and (name == 'dead' or name == 'lost' or name == 'crash') then
    d.despawned = true
  end
  SORTIE.emit(name, d)
  if name == 'mission_end' then
    if SORTIE.warehouse then SORTIE.safe('wh.report', SORTIE.warehouse.report, 'end') end
    SORTIE.close()
  end
end

world.addEventHandler({
  onEvent = function(_, event)
    SORTIE.safe('event', SORTIE.events.handle, event)
  end,
})

-- Periodic snapshot: counts per coalition/category and every player's state.
local categories = { air = Group.Category.AIRPLANE, helo = Group.Category.HELICOPTER,
                     ground = Group.Category.GROUND, ship = Group.Category.SHIP }

function SORTIE.events.snapshot()
  local snap = { counts = {}, players = {} }
  for label, side in pairs({ red = coalition.side.RED, blue = coalition.side.BLUE }) do
    local c = {}
    for cat, id in pairs(categories) do
      local n = 0
      local ok, groups = pcall(coalition.getGroups, side, id)
      if ok and groups then
        for _, g in ipairs(groups) do
          local okSize, size = pcall(g.getSize, g)
          if okSize and size then n = n + size end
        end
      end
      c[cat] = n
    end
    snap.counts[label] = c
  end
  for _, u in ipairs(SORTIE.players()) do
    local p = SORTIE.ref(u) or {}
    p.pos = SORTIE.latlon(u)
    pcall(function() p.air = u:inAir() end)
    pcall(function() p.fuel = u:getFuel() end)
    pcall(function() p.life = u:getLife() end)
    snap.players[#snap.players + 1] = p
  end
  SORTIE.emit('snapshot', snap)
end

SORTIE.every(SORTIE.cfg.snapshot_interval or 30, 'snapshot', SORTIE.events.snapshot)
