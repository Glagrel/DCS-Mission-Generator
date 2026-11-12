"""Deck statics, JTAC autolase and the Skynet / Hound set-up, run under real Lua with the DCS mock."""
import json

from sortie.mission import scripts
from tests.luaenv import LUA, LuaEnv

BASE = {"version": 1, "campaign": "t", "turn": 1, "sortie": "s", "player_side": 2, "player_group": "S|flt|P|1",
        "runtime_subdir": "Missions\\SORTIE\\runtime\\", "events_file": "events.jsonl", "snapshot_interval": 30,
        "spawn_m": 50000.0, "despawn_m": 80000.0, "manifest": {}, "late_groups": [], "atc": {"enabled": False}}

# A carrier at the origin heading north (+x). Spots: two to starboard (z > 12) aft of the bow,
# one on the centreline (catapult run), one to port (landing area), one starboard on the bow
# catapults' run (x > 60), one taken by an aircraft.
SHIP = """
SHIP = MOCK.unit{ name = 'CVN #1', type = 'CVN_73', coalition = 2, x = 0, z = 0, id = 501 }
MOCK.group{ name = 'S|nav|cvn|1', side = 2, cat = Group.Category.SHIP, units = { SHIP } }
AB = MOCK.airbase('CVN #1')
AB.spots = {
  { Term_Index = 1, vTerminalPos = { x = -40, y = 20, z = 25 } },
  { Term_Index = 2, vTerminalPos = { x = 10, y = 20, z = 30 } },
  { Term_Index = 3, vTerminalPos = { x = 20, y = 20, z = 0 } },
  { Term_Index = 4, vTerminalPos = { x = -60, y = 20, z = -20 } },
  { Term_Index = 5, vTerminalPos = { x = 90, y = 20, z = 20 } },
  { Term_Index = 6, vTerminalPos = { x = -20, y = 20, z = 28 }, TO_AC = true },
  { Term_Index = 7, vTerminalPos = { x = -80, y = 20, z = 14 } },
}
"""


def _events(env):
    if not env.events_path.is_file():
        return []
    return [json.loads(x) for x in env.events_path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _env(tmp_path, cfg, setup=SHIP, extra=None):
    names = list(scripts.CORE_SCRIPTS) + (extra or [])
    return LuaEnv(tmp_path, scripts.config_lua({**BASE, **cfg}), setup=setup, scripts=names)


def test_deck_statics_only_on_safe_free_spots_and_keep_reserve(tmp_path):
    deck = [{"carrier_unit": "CVN #1", "kind": "cvn", "types": ["F-14B", "E-2C", "FA-18C_hornet", "S-3B Tanker"],
             "max": 4, "reserve": 3}]
    env = _env(tmp_path, {"deck": deck})
    env.run("MOCK.advance(5)")
    placed = env.eval("#MOCK.statics")
    # 6 free spots - 3 reserved = 3 may be filled; safe ones: #1, #2, #7 (starboard, aft of the bow cats)
    assert placed == 3
    offs = sorted((env.eval(f"MOCK.statics[{i}].offsets.x"), env.eval(f"MOCK.statics[{i}].offsets.y"))
                  for i in range(1, placed + 1))
    assert offs == [(-80.0, 14.0), (-40.0, 25.0), (10.0, 30.0)]
    assert env.eval("MOCK.statics[1].linkUnit") == 501 and env.eval("MOCK.statics[1].linkOffset") is True
    assert env.eval("MOCK.statics[1].type") == "F-14B"
    ev = [e for e in _events(env) if e.get("ev") == "deck"]
    assert ev and ev[0]["placed"] == 3 and ev[0]["reserve"] == 3


def test_deck_never_eats_into_reserve(tmp_path):
    deck = [{"carrier_unit": "CVN #1", "kind": "cvn", "types": ["F-14B"] * 8, "max": 8, "reserve": 6}]
    env = _env(tmp_path, {"deck": deck})
    env.run("MOCK.advance(5)")
    assert env.eval("#MOCK.statics") == 0           # 6 free, 6 reserved: nothing parked


def test_jtac_without_moose_uses_dcs_fac(tmp_path):
    env = _env(tmp_path, {"jtacs": [{"group": "S|jtac|B1-01|1", "callsign": "Axeman 1-1", "code": "1688",
                                     "autolase": True}]}, setup="")
    ev = [e for e in _events(env) if e.get("ev") == "support" and e.get("role") == "jtac"]
    assert ev and ev[0]["by"] == "fac"


SKYNET_STUB = """
CALLS = {}
local function rec(...) CALLS[#CALLS + 1] = table.concat({...}, ' ') end
SkynetIADSAbstractRadarElement = { GO_LIVE_WHEN_IN_SEARCH_RANGE = 2 }
SkynetIADS = {}
function SkynetIADS:create(name)
  rec('create', name)
  local site = {}
  function site:setGoLiveRangeInPercent(p) rec('golive', p) end
  function site:setEngagementZone(z) rec('zone', z) end
  function site:setHARMDetectionChance(c) rec('harm', c) end
  function site:addPointDefence(s) rec('pd') end
  local iads = {}
  function iads:setUpdateInterval(s) rec('interval', s) end
  function iads:addSAMSite(g) rec('sam', g); return site end
  function iads:addEarlyWarningRadar(u) rec('ewr', u) end
  function iads:getDebugSettings() return {} end
  function iads:addRadioMenu() rec('menu') end
  function iads:activate() rec('activate') end
  return iads
end
HOUND = { MARKER = { CIRCLE = 4 }, DB = { Platform = { [1] = { ['E-3A'] = {} } } } }
function HOUND.setMgrsPresicion() end
HoundElint = {}
function HoundElint:create(side)
  rec('hound', side)
  local h = {}
  setmetatable(h, { __index = function(_, k) return function(_, a) rec('h.' .. k, tostring(a)) end end })
  return h
end
AW = MOCK.unit{ name = 'Darkstar-1', type = 'E-3A', coalition = 2, air = true }
MOCK.group{ name = 'S|flt|AW|1', side = 2, units = { AW } }
"""


def test_skynet_and_hound_setup(tmp_path):
    addons = {
        "skynet": {"go_live_pct": 80, "engagement_zone": "search", "harm_detection": 40, "point_defence": True,
                   "awacs_as_ew": True, "update_interval": 5, "radio_menu": True, "ai_jammers": False,
                   "networks": [{"name": "RED", "sites": [{"group": "S|sam|sa10|1"}, {"group": "S|sam|sa15|1"}],
                                 "ewr_units": ["S|sam|ewr|1 #1"],
                                 "point_defence": [{"site": "S|sam|sa10|1", "defender": "S|sam|sa15|1"}],
                                 "awacs_units": [], "jammer_units": []}]},
        "hound": {"side": 2, "markers": True, "marker_type": "CIRCLE", "site_markers": True, "bda": True,
                  "text": True, "prebriefed": ["S|sam|sa10|1"], "nato_names": True, "scan_interval": 5},
    }
    env = _env(tmp_path, {"addons": addons}, setup=SKYNET_STUB, extra=["sortie_addons.lua"])
    env.run("MOCK.advance(15)")
    calls = [env.eval(f"CALLS[{i}]") for i in range(1, env.eval("#CALLS") + 1)]
    assert "create RED" in calls and "sam S|sam|sa10|1" in calls and "ewr S|sam|ewr|1 #1" in calls
    assert "golive 80" in calls and "zone 2" in calls and "harm 40" in calls and "pd" in calls
    assert "menu" in calls and calls.index("activate") > calls.index("sam S|sam|sa15|1")
    assert "hound 2" in calls and "h.preBriefedContact S|sam|sa10|1" in calls and "h.systemOn nil" in calls
    assert "h.addPlatform Darkstar-1" in calls                    # airborne E-3A picked up as a platform
    assert not env.eval("#MOCK.errors")


def test_addon_setup_is_harmless_without_the_scripts(tmp_path):
    env = _env(tmp_path, {"addons": {"skynet": {"networks": []}, "hound": {"side": 2}}}, setup="",
               extra=["sortie_addons.lua"])
    env.run("MOCK.advance(20)")
    assert not env.eval("#MOCK.errors")
    assert (LUA / "sortie_addons.lua").is_file()
