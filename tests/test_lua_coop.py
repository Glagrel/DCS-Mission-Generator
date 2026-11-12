"""Lua: event-file location fallbacks, the in-game link notice, messages to every human
group, carrier support wiring."""
import json

from sortie.mission import scripts
from tests.luaenv import LuaEnv
from tests.test_lua import CFG, SETUP

TWO = SETUP + """
P2 = MOCK.unit{ name = 'S|flt|B3-04-1|1 Pilot #2', type = 'A-10C_2', coalition = 2, player = 'Goose' }
MOCK.group{ name = 'S|flt|B3-04-1|1', side = 2, units = { P2 }, id = 9 }
"""


def test_messages_reach_every_client_group(tmp_path):
    cfg = {**CFG, "client_groups": ["S|flt|B3-01-1|1", "S|flt|B3-04-1|1"]}
    env = LuaEnv(tmp_path, scripts.config_lua(cfg), setup=TWO)
    env.run("SORTIE.message('push', 5)")
    groups = sorted(v.group for v in env.eval("MOCK.texts").values() if v.text == "push")
    assert groups == [7, 9] and env.errors() == []


def test_link_notice_is_shown_once_working(tmp_path):
    env = LuaEnv(tmp_path, scripts.config_lua(CFG), setup=SETUP)
    env.run("MOCK.advance(11)")
    texts = [v.text for v in env.eval("MOCK.texts").values()]
    assert any("campaign link active" in t for t in texts)
    assert env.events()[0]["path"].endswith("events.jsonl")


def test_link_notice_explains_when_sanitised(tmp_path):
    env = LuaEnv(tmp_path, scripts.config_lua(CFG), sanitized=True, setup=SETUP)
    env.run("MOCK.advance(11)")
    texts = [v.text for v in env.eval("MOCK.texts").values()]
    assert any("install_desanitize" in t for t in texts) and env.errors() == []


def test_absolute_event_dir_is_preferred_and_needs_only_io(tmp_path):
    """Like Retribution: try the folder the app passed in first; lfs is optional."""
    target = tmp_path / "given"
    target.mkdir()
    cfg = {**CFG, "event_dirs": [str(tmp_path / "missing_dir") + "\\", str(target) + "\\"]}
    env = LuaEnv(tmp_path, scripts.config_lua(cfg), setup="lfs = nil\n" + SETUP)
    assert env.eval("SORTIE.mode") == "file" and env.errors() == []
    assert env.eval("SORTIE.path") == str(target) + "\\events.jsonl"
    env.run("SORTIE.file:flush()")
    first = json.loads((target / "events.jsonl").read_text().splitlines()[0])
    assert first["ev"] == "mission_start" and first["mode"] == "file"


def test_falls_back_to_writedir_when_given_dirs_fail(tmp_path):
    cfg = {**CFG, "event_dirs": [str(tmp_path / "nope") + "\\"]}
    env = LuaEnv(tmp_path, scripts.config_lua(cfg), setup=SETUP)
    assert env.eval("SORTIE.mode") == "file" and env.events()[0]["ev"] == "mission_start"


def test_plane_guard_uses_moose_when_present_else_own_route(tmp_path):
    cfg = {**CFG, "carrier_support": [{"role": "plane_guard", "group": "S|flt|B3-02-1|1",
                                       "carrier_unit": "S|nav|cvn73|1 #1", "moose": True}]}
    helo = """
    H1 = MOCK.unit{ name = 'S|flt|B3-02-1|1 Pilot #1', type = 'SH-60B', coalition = 2, air = true }
    MOCK.group{ name = 'S|flt|B3-02-1|1', side = 2, cat = Group.Category.HELICOPTER, units = { H1 }, late = true }
    """
    moose = """
    RESCUEHELO = {}
    function RESCUEHELO:New(carrier, group) local o = { carrier = carrier, group = group }; setmetatable(o, { __index = RESCUEHELO }); MOCK.helo = o; return o end
    function RESCUEHELO:SetTakeoffAir() self.air = true end
    function RESCUEHELO:SetRespawnOff() self.norespawn = true end
    function RESCUEHELO:Start() self.started = true end
    """
    env = LuaEnv(tmp_path / "a", scripts.config_lua(cfg), setup=SETUP + helo + moose)
    assert env.eval("MOCK.helo.started") is True and env.eval("MOCK.helo.carrier") == "S|nav|cvn73|1 #1"
    assert env.eval("MOCK.helo.air") is True and env.eval("MOCK.helo.norespawn") is True
    assert [e["by"] for e in env.events() if e["ev"] == "support"] == ["moose"]
    env = LuaEnv(tmp_path / "b", scripts.config_lua(cfg), setup=SETUP + helo)      # MOOSE not loaded
    assert env.eval("MOCK.groups['S|flt|B3-02-1|1'].active") is True                # flies its own racetrack
    assert [e["by"] for e in env.events() if e["ev"] == "support"] == ["route"] and env.errors() == []


def test_human_flights_and_support_are_never_despawned(tmp_path):
    cfg = json.loads(json.dumps(CFG))
    cfg["manifest"]["S|flt|B3-04-1|1"] = {"kind": "flight", "id": "B3-04-1", "units": 2, "player": False,
                                          "clients": ["S|flt|B3-04-1|1 Pilot #2"]}
    cfg["manifest"]["S|flt|R3-02-1|1"]["role"] = "recovery_tanker"
    env = LuaEnv(tmp_path, scripts.config_lua(cfg), setup=TWO)
    env.run("P2.x = 900000; E1.air = true; MOCK.advance(50); E1.air = false; P2.air = false; MOCK.advance(600)")
    assert env.eval("MOCK.groups['S|flt|B3-04-1|1'].exists") is True
    assert env.eval("MOCK.groups['S|flt|R3-02-1|1'].exists") is True


def test_limited_munitions_stocks_catalog_and_name_variants(tmp_path):
    """Experimental limited weapons: everything DCS lists gets stock, including fuel tanks, and
    ammo type names without a category prefix are tried with the usual prefixes."""
    setup = SETUP + """
    Warehouse = { getResourceMap = function() return {
      ['weapons.droptanks.FPU_8A'] = { 1, 3, 43, 12 }, ['weapons.missiles.AIM_9X'] = { 4, 4, 7, 136 },
      nested = { ['weapons.containers.AN_ASQ_228'] = true } } end }
    P1.ammo = { AIM_9X = 2 }
    MOCK.airbases['Al Dhafra AFB'].wh.weapon = {}
    """
    env = LuaEnv(tmp_path, scripts.config_lua(CFG), setup=setup)
    wh = "MOCK.airbases['Al Dhafra AFB'].wh.weapon"
    assert env.eval(wh + "['weapons.droptanks.FPU_8A']") == 40
    assert env.eval(wh + "['weapons.containers.AN_ASQ_228']") == 40
    assert env.eval(wh + "['weapons.missiles.AIM_9X']") == 40
    dbg = [e for e in env.events() if e["ev"] == "warehouse_debug"][0]
    assert dbg["resource_map"] == "table" and dbg["items"] == 3 and env.errors() == []
    assert env.eval("#SORTIE.warehouse.variants('AIM_9X')") == 9
    assert env.eval("#SORTIE.warehouse.variants('weapons.missiles.AIM_120C')") == 1


def test_resource_map_unavailable_is_reported_not_fatal(tmp_path):
    env = LuaEnv(tmp_path, scripts.config_lua(CFG), setup=SETUP)          # no Warehouse global at all
    dbg = [e for e in env.events() if e["ev"] == "warehouse_debug"][0]
    assert dbg["resource_map"] == "unavailable" and dbg["items"] == 0 and env.errors() == []
