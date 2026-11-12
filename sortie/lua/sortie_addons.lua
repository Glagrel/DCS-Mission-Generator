-- SORTIE set-up for the optional community scripts (Skynet IADS, Hound ELINT, Growler AEA).
-- Loaded after the scripts themselves. Everything SORTIE knows about the mission (which groups
-- are SAM sites, which are early-warning radars, which flights are AI jammers, which sites the
-- campaign already knows) comes in SORTIE.cfg.addons, built from the mission manifest.
-- Every call is guarded: a script that is missing or changed its API must never stop SORTIE.
SORTIE.addons = SORTIE.addons or { iads = {}, hound = nil }

local A = SORTIE.cfg.addons or {}

local function alive_unit(name)
  local u = Unit.getByName(name)
  if u and u:isExist() then return u end
  return nil
end

-- ---- Skynet IADS ------------------------------------------------------------------------------
function SORTIE.addons.skynet()
  local cfg = A.skynet
  if not cfg or not SkynetIADS then return end
  for _, net in ipairs(cfg.networks or {}) do
    local iads = SkynetIADS:create(net.name)
    pcall(function() iads:setUpdateInterval(cfg.update_interval or 5) end)
    local sites = {}
    for _, s in ipairs(net.sites or {}) do
      local ok, site = pcall(function() return iads:addSAMSite(s.group) end)
      if ok and site then
        sites[s.group] = site
        pcall(function()
          if (cfg.go_live_pct or 100) ~= 100 then site:setGoLiveRangeInPercent(cfg.go_live_pct) end
          if cfg.engagement_zone == 'search' then
            site:setEngagementZone(SkynetIADSAbstractRadarElement.GO_LIVE_WHEN_IN_SEARCH_RANGE)
          end
          if (cfg.harm_detection or -1) >= 0 then site:setHARMDetectionChance(cfg.harm_detection) end
        end)
      else
        SORTIE.log('Skynet: could not add SAM site ' .. tostring(s.group) .. ' ' .. tostring(site))
      end
    end
    for _, u in ipairs(net.ewr_units or {}) do
      pcall(function() iads:addEarlyWarningRadar(u) end)
    end
    if cfg.awacs_as_ew then
      for _, u in ipairs(net.awacs_units or {}) do
        if alive_unit(u) then pcall(function() iads:addEarlyWarningRadar(u) end) end
      end
    end
    if cfg.point_defence then
      for _, pd in ipairs(net.point_defence or {}) do
        local big, small = sites[pd.site], sites[pd.defender]
        if big and small then pcall(function() big:addPointDefence(small) end) end
      end
    end
    if cfg.debug_status then
      pcall(function() local d = iads:getDebugSettings(); d.IADSStatus = true; d.contacts = true end)
    end
    if cfg.radio_menu then pcall(function() iads:addRadioMenu() end) end
    local ok, err = pcall(function() iads:activate() end)
    SORTIE.addons.iads[#SORTIE.addons.iads + 1] = iads
    SORTIE.emit('addon', { name = 'skynet', network = net.name, sites = #(net.sites or {}),
                           ok = ok, err = (not ok) and tostring(err) or nil })
    -- AI jammers of the other side work against this network
    if cfg.ai_jammers and SkynetIADSJammer then
      for _, u in ipairs(net.jammer_units or {}) do
        SORTIE.addons.watch_jammer(u, iads, cfg.jammer_range_nm or 160)
      end
    end
  end
end

-- A jammer flight may still be parked or not yet started: attach it once it is airborne.
function SORTIE.addons.watch_jammer(unit_name, iads, range_nm)
  local tries = 0
  local function try()
    tries = tries + 1
    local u = alive_unit(unit_name)
    if u and u:inAir() then
      local ok, err = pcall(function()
        local j = SkynetIADSJammer:create(u, iads)
        j:setMaximumEffectiveDistance(range_nm)
        j:masterArmOn()
      end)
      SORTIE.emit('addon', { name = 'skynet_jammer', unit = unit_name, ok = ok, err = (not ok) and tostring(err) or nil })
      return nil
    end
    if tries > 360 then return nil end            -- give up after ~3 hours
    return timer.getTime() + 30
  end
  timer.scheduleFunction(function() return try() end, nil, timer.getTime() + 5)
end

-- ---- Hound ELINT -----------------------------------------------------------------------------------
function SORTIE.addons.hound()
  local cfg = A.hound
  if not cfg or not HoundElint then return end
  local side = cfg.side == 1 and coalition.side.RED or coalition.side.BLUE
  local ok, err = pcall(function()
    if HOUND and HOUND.setMgrsPresicion then HOUND.setMgrsPresicion(5) end
    local h = HoundElint:create(side)
    SORTIE.addons.hound_instance = h
    if cfg.scan_interval then pcall(function() h:setTimerInterval('scan', cfg.scan_interval) end) end
    if cfg.markers then
      h:enableMarkers()
      pcall(function() h:setMarkerType(HOUND.MARKER[cfg.marker_type or 'CIRCLE']) end)
    else
      h:disableMarkers()
    end
    if cfg.site_markers then pcall(function() h:enableSiteMarkers() end) else pcall(function() h:disableSiteMarkers() end) end
    if cfg.bda then pcall(function() h:enableBDA() end) else pcall(function() h:disableBDA() end) end
    pcall(function() h:setAlertOnLaunch(cfg.alert_on_launch and true or false) end)
    pcall(function() h:useNATOCallsigns(cfg.nato_names and true or false) end)
    if cfg.nato_names then pcall(function() h:enableNATO() end) end
    if cfg.pos_errors then pcall(function() h:enablePlatformPosErrors() end) end
    if cfg.text then pcall(function() h:enableText('all') end); pcall(function() h:enableController() end) end
    for _, name in ipairs(cfg.prebriefed or {}) do pcall(function() h:preBriefedContact(name) end) end
    h:systemOn()
  end)
  SORTIE.emit('addon', { name = 'hound', ok = ok, err = (not ok) and tostring(err) or nil })
  if ok then SORTIE.addons.hound_platforms() end
end

-- Add every friendly unit Hound can use as a platform; repeat as flights take off and spawn.
function SORTIE.addons.hound_platforms()
  local h, cfg = SORTIE.addons.hound_instance, A.hound
  if not h or not HOUND or not HOUND.DB or not HOUND.DB.Platform then return end
  local side = cfg.side == 1 and coalition.side.RED or coalition.side.BLUE
  local known = HOUND.DB.Platform[Object.Category.UNIT] or {}
  SORTIE.addons.hound_added = SORTIE.addons.hound_added or {}
  local function scan()
    for _, cat in ipairs({ Group.Category.AIRPLANE, Group.Category.HELICOPTER, Group.Category.GROUND }) do
      for _, g in ipairs(coalition.getGroups(side, cat) or {}) do
        for _, u in ipairs(g:getUnits() or {}) do
          local n = u:getName()
          if not SORTIE.addons.hound_added[n] and known[u:getTypeName()] and (cat == Group.Category.GROUND or u:inAir()) then
            local ok, res = pcall(function() return h:addPlatform(n) end)
            if ok and res ~= false then SORTIE.addons.hound_added[n] = true end
          end
        end
      end
    end
    return timer.getTime() + 60
  end
  timer.scheduleFunction(function() return scan() end, nil, timer.getTime() + 10)
end

-- ---- start -------------------------------------------------------------------------------------------
SORTIE.safe('addons.skynet', SORTIE.addons.skynet)
SORTIE.safe('addons.hound', SORTIE.addons.hound)
