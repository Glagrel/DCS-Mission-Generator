-- SORTIE proximity manager.
--  * Late-activated ground groups (cfg.late_groups) are activated when a player comes
--    within cfg.spawn_m of them.
--  * AI flights that are finished (past their planned end time, or landed) and farther than
--    cfg.despawn_m from every player are removed. Their units are recorded in
--    SORTIE.despawned and a 'despawn' event is written BEFORE the group is destroyed, so the
--    campaign never counts them as losses.
SORTIE.spawn = { pending = {}, air = {}, landed = {} }
local S = SORTIE.spawn

local function point_of(entry)
  -- manifest carries lat/lon; convert once to map coordinates
  if not entry.p and entry.lat and entry.lon then
    local ok, p = pcall(coord.LLtoLO, entry.lat, entry.lon, 0)
    if ok then entry.p = p end
  end
  return entry.p
end

local function nearest_player_m(p, players)
  local best = nil
  for _, u in ipairs(players) do
    local ok, up = pcall(u.getPoint, u)
    if ok and up then
      local d = SORTIE.dist2d(p, up)
      if not best or d < best then best = d end
    end
  end
  return best
end

function S.init()
  local man = SORTIE.cfg.manifest or {}
  for _, name in ipairs(SORTIE.cfg.late_groups or {}) do
    if man[name] then S.pending[name] = man[name] end
  end
  for name, entry in pairs(man) do
    if entry.kind == 'flight' and not entry.player then S.air[name] = entry end
  end
end

function S.activate(name, entry, dist)
  local g = Group.getByName(name)
  if g then
    g:activate()
    SORTIE.emit('spawn', { g = name, kind = entry.kind, entity = entry.id, dist = dist })
  end
  S.pending[name] = nil
end

function S.despawn(name, entry, reason)
  local g = Group.getByName(name)
  if not g or not g:isExist() then S.air[name] = nil; return end
  local units = {}
  for _, u in ipairs(g:getUnits() or {}) do
    local n = u:getName()
    units[#units + 1] = n
    SORTIE.despawned[n] = true
  end
  SORTIE.emit('despawn', { g = name, kind = entry.kind, entity = entry.id, units = units, reason = reason })
  g:destroy()
  S.air[name] = nil
end

function S.tick()
  local players = SORTIE.players()
  if #players == 0 then return end
  local now = timer.getTime()
  for name, entry in pairs(S.pending) do
    local p = point_of(entry)
    if p then
      local d = nearest_player_m(p, players)
      if d and d <= (SORTIE.cfg.spawn_m or 100000) then S.activate(name, entry, d) end
    else
      S.activate(name, entry, -1)     -- no position known: fail safe and show the group
    end
  end
  for name, entry in pairs(S.air) do
    local g = Group.getByName(name)
    if g and g:isExist() then
      local units = g:getUnits() or {}
      local u = units[1]
      if u then
        local airborne = u:inAir()
        if not airborne and entry.took_off then
          S.landed[name] = S.landed[name] or now
        elseif airborne then
          entry.took_off = true
          S.landed[name] = nil
        end
        local d = nearest_player_m(u:getPoint(), players)
        local far = d and d > (SORTIE.cfg.despawn_m or 130000)
        local finished = entry.end_s and now > entry.end_s + 300
        local parked = S.landed[name] and now - S.landed[name] > 180
        if far and (finished or parked) then
          S.despawn(name, entry, parked and 'landed' or 'finished')
        end
      end
    end
  end
end

SORTIE.safe('spawn.init', S.init)
SORTIE.every(10, 'spawn.tick', S.tick)
SORTIE.log('scripts loaded (mode ' .. SORTIE.mode .. ')')
