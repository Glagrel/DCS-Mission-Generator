"""End-to-end: database -> theater -> campaign -> ATO -> mission -> simulated events ->
debrief -> career -> war turn -> next assignment, for several turns and every theater.
Also exercises tools/install_desanitize.ps1 against a FAKE install in a temp folder."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sortie import config
from sortie.campaign import CareerOptions
from sortie.db import Store
from sortie.mission import loadouts
from sortie.runtime import simulate
from sortie.service import Service
from tests.conftest import PLAYER

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "install_desanitize.ps1"
ORIGINAL = """--Initialization script for the Mission lua Environment (SSE)

dofile('Scripts/ScriptingSystem.lua')

--Sanitize Mission Scripting environment
--This makes unavailable some unsecure functions.
do
\tsanitizeModule('os')
\tsanitizeModule('io')
\tsanitizeModule('lfs')
\t_G['require'] = nil
\t_G['loadlib'] = nil
\t_G['package'] = nil
end
"""


def _service(tmp_path):
    s = config.Settings(saved_games=str(tmp_path / "sg" / "DCS.openbeta"), dcs_install=str(tmp_path / "none"),
                        output_dir=str(tmp_path / "out"), db_path=str(tmp_path / "db" / "sortie.db"))
    loadouts.configure(None)
    return Service(Store(s.db_path), s)                                 # 1. initialise the database


def _write_events(svc, cid, outcome="success"):
    st = svc.state(cid)
    ev = simulate.simulate(simulate.manifest_with_sides(st.sortie.summary["manifest"], st),
                           st.sortie.summary["sortie_id"], st.sortie.summary["player_group"], st.meta.turn,
                           seed=st.meta.turn, outcome=outcome)
    p = svc.events_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(e) + "\n" for e in ev), encoding="utf-8")
    return ev


@pytest.mark.parametrize("tid", ["gulf_crisis", "coldwar_1985", "forager_1944"])
def test_full_campaign_flow(tmp_path, tid):
    svc = _service(tmp_path)
    side, sq = PLAYER[tid]
    cid = svc.new_campaign(CareerOptions(theater_id=tid, side=side, squadron_id=sq,   # 2-5 theater, campaign,
                                         callsign="Rook", seed=11))                   #     pilot, squadron
    st = svc.state(cid)                                                               # 6. campaign state
    assert st.pilot.squadron_id == sq and st.meta.turn == 1
    seen_tasks = set()
    for turn in range(1, 5):
        brief = svc.plan(cid)                                                         # 7-8. ATO + assignment
        assert brief["assigned"] and brief["turn"] == turn and brief["reason"]
        seen_tasks.add(brief["mission"])
        res = svc.generate_mission(cid, with_moose=False)                             # 9. mission
        assert Path(res.path).is_file() and res.filename.endswith(f"T{turn:03d}.miz")
        assert str(tmp_path) in res.path                                              # never outside the sandbox
        ev = _write_events(svc, cid)                                                  # 10. simulated events
        assert svc.poll_live(cid)["count"] == len(ev)
        deb = svc.debrief(cid)                                                        # 11-14
        assert deb["turn"] == turn and deb["state"] == "flown" and deb["next"]["turn"] == turn + 1
        assert deb["pilot"]["sorties"] == turn and deb["war"]["supply"]["produced"]
        st = svc.state(cid)
        if st.meta.status != "active":
            break
    st = svc.state(cid)
    assert st.pilot.sorties >= 1 and st.pilot.hours > 0 and len(st.pilot.history) >= st.pilot.sorties
    assert st.pilot.aircraft in st.meta.owned_modules                                  # ownership always holds
    assert sum(s.sorties_flown for s in st.squadrons.values()) > 0
    assert sum(s.losses for s in st.squadrons.values()) > 0                            # the war has attrition
    assert all(0 <= f.position <= 1 for f in st.fronts.values())
    assert all(b.fuel.jet >= 0 and b.fuel.avgas >= 0 and 0 <= b.munition_level <= 1 for b in st.airbases.values())
    assert all(s.airframes >= 0 and s.pilots >= 0 for s in st.squadrons.values())
    assert len(svc.store.history(cid, "debrief")) >= 1 and seen_tasks
    if st.meta.status == "active":
        nxt = svc.plan(cid)                                                           # 15. next assignment
        assert nxt["turn"] == st.meta.turn and ("assigned" in nxt)


def test_state_survives_application_restart(tmp_path):
    svc = _service(tmp_path)
    cid = svc.new_campaign(CareerOptions(theater_id="gulf_crisis", squadron_id="77fs", callsign="Rook", seed=2))
    svc.generate_mission(cid, with_moose=False)
    _write_events(svc, cid)
    svc.poll_live(cid)
    svc.store.close()
    svc2 = Service(Store(svc.settings.db_path), svc.settings)           # "restart"
    assert svc2.poll_live(cid)["events"] == []                           # cursor persisted: nothing replayed
    deb = svc2.debrief(cid)
    assert deb["state"] == "flown" and svc2.state(cid).pilot.sorties == 1
    assert svc2.state(cid).meta.turn == 2


def test_long_campaign_stays_consistent(tmp_path):
    """Twelve cycles without the player: the abstract war must stay sane."""
    svc = _service(tmp_path)
    cid = svc.new_campaign(CareerOptions(theater_id="coldwar_1985", squadron_id="53tfs", callsign="Rook", seed=5))
    for _ in range(12):
        if svc.state(cid).meta.status != "active":
            break
        svc.skip(cid)
    st = svc.state(cid)
    assert st.meta.turn >= 2
    assert any(s.airframes < s.airframes_max for s in st.squadrons.values())
    assert any(abs(f.position - p) > 0.001 for f, p in zip(st.fronts.values(), (0.62, 0.5)))
    assert all(0 <= n.health <= 1 and n.stock >= 0 for n in st.supply_nodes.values())
    assert all(0 <= s.health <= 1 for s in st.sam_sites.values())


# ---- tools/install_desanitize.ps1 on a fake install -----------------------------------------------
def _ps(*args):
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        pytest.skip("PowerShell not available")
    return subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def fake_dcs(tmp_path):
    root = tmp_path / "FakeDCS"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "DCS.exe").write_text("")
    (root / "Scripts").mkdir()
    (root / "Scripts" / "MissionScripting.lua").write_text(ORIGINAL)
    return root


def test_desanitize_apply_and_undo(fake_dcs):
    target = fake_dcs / "Scripts" / "MissionScripting.lua"
    backup = Path(str(target) + ".sortie-backup")
    r = _ps("-DcsPath", str(fake_dcs), "-DryRun")
    assert r.returncode == 0 and "DRY RUN" in r.stdout and target.read_text() == ORIGINAL and not backup.exists()
    r = _ps("-DcsPath", str(fake_dcs))
    assert r.returncode == 0 and "SUCCESS" in r.stdout
    text = target.read_text()
    live = [ln for ln in text.splitlines() if ln.strip().startswith("sanitizeModule(")]
    assert live == [] and text.count("-- SORTIE desanitize: sanitizeModule(") == 3
    assert "_G['require'] = nil" in text and "\t_G['loadlib'] = nil" in text      # untouched
    assert backup.read_text() == ORIGINAL
    r = _ps("-DcsPath", str(fake_dcs))                                             # second run is harmless
    assert r.returncode == 0 and "Already desanitised" in r.stdout and backup.read_text() == ORIGINAL
    r = _ps("-DcsPath", str(fake_dcs), "-Undo")
    assert r.returncode == 0 and target.read_text() == ORIGINAL and backup.exists()


def test_desanitize_keeps_existing_backup_and_undoes_without_one(fake_dcs):
    target = fake_dcs / "Scripts" / "MissionScripting.lua"
    backup = Path(str(target) + ".sortie-backup")
    backup.write_text("precious")
    r = _ps("-DcsPath", str(fake_dcs))
    assert r.returncode == 0 and "NOT overwritten" in r.stdout and backup.read_text() == "precious"
    backup.unlink()
    r = _ps("-DcsPath", str(fake_dcs), "-Undo")                                    # no backup: uncomment in place
    assert r.returncode == 0 and target.read_text().replace("\r\n", "\n").count("\tsanitizeModule(") == 0
    assert [ln.strip() for ln in target.read_text().splitlines() if "sanitizeModule('io')" in ln] == ["sanitizeModule('io')"]


def test_desanitize_rejects_bad_paths(tmp_path, fake_dcs):
    r = _ps("-DcsPath", str(tmp_path / "nowhere"))
    assert r.returncode == 1 and "FAILED" in r.stdout
    (fake_dcs / "Scripts" / "MissionScripting.lua").write_text("-- nothing to see\n")
    r = _ps("-DcsPath", str(fake_dcs))
    assert r.returncode == 1 and "nothing was modified" in r.stdout
