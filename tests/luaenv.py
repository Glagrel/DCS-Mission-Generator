"""Run SORTIE's Lua under real Lua 5.1 (lupa) with a mocked DCS API."""
import json
from pathlib import Path

import pytest

lua51 = pytest.importorskip("lupa.lua51")

ROOT = Path(__file__).resolve().parent.parent
LUA = ROOT / "sortie" / "lua"
MOCK = Path(__file__).resolve().parent / "lua_mock.lua"
CORE = ["sortie_json.lua", "sortie_core.lua", "sortie_events.lua", "sortie_warehouse.lua", "sortie_spawn.lua"]


class LuaEnv:
    def __init__(self, tmp_path, cfg_lua: str, sanitized: bool = False, setup: str = "", scripts=None):
        self.dir = tmp_path / "sg"
        (self.dir / "Missions" / "SORTIE" / "runtime").mkdir(parents=True, exist_ok=True)
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.MOCK_DIR = str(self.dir) + "\\"
        g.MOCK_SANITIZED = sanitized
        self.run(MOCK.read_text(encoding="utf-8"))
        self.run(setup)                 # world state that exists before the scripts load
        self.run(cfg_lua)
        for name in scripts or CORE:
            self.run((LUA / name).read_text(encoding="utf-8"), name)

    def run(self, code: str, name: str = "chunk"):
        if code:
            return self.lua.execute(code)

    def eval(self, expr: str):
        return self.lua.eval(expr)

    @property
    def events_path(self) -> Path:
        return self.dir / "Missions" / "SORTIE" / "runtime" / "events.jsonl"

    def events(self):
        self.run("if SORTIE.file then SORTIE.file:flush() end")
        if not self.events_path.exists():
            return []
        return [json.loads(line) for line in self.events_path.read_text(encoding="utf-8").splitlines() if line]

    def log_events(self):
        """Events written to the (mock) dcs.log in sanitised mode."""
        out = []
        for line in self.lua.eval("MOCK.log").values():
            if line.startswith("SORTIE_EVT "):
                out.append(json.loads(line[len("SORTIE_EVT "):]))
        return out

    def errors(self):
        return list(self.lua.eval("MOCK.errors").values())
