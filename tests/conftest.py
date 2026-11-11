import pytest

from sortie import config, theater
from sortie.campaign import CareerOptions, build_state
from sortie.db import Store

PLAYER = {"coldwar_1985": ("blue", "53tfs"), "forager_1944": ("blue", "vf15"), "gulf_crisis": ("blue", "77fs")}


@pytest.fixture(scope="session")
def theaters():
    return {t.id: t for t in theater.list_theaters()}


@pytest.fixture
def settings(tmp_path):
    return config.Settings(saved_games=str(tmp_path / "SavedGames" / "DCS.openbeta"),
                           db_path=str(tmp_path / "sortie.db"), output_dir=str(tmp_path / "out"))


def make_state(theaters, tid="gulf_crisis", side=None, squadron=None, seed=7, settings=None):
    s, q = PLAYER[tid]
    opt = CareerOptions(theater_id=tid, side=side or s, squadron_id=squadron or q, callsign="Rook", seed=seed)
    return build_state(theaters[tid], opt, settings)


@pytest.fixture
def gulf(theaters):
    return make_state(theaters, "gulf_crisis")


@pytest.fixture
def coldwar(theaters):
    return make_state(theaters, "coldwar_1985")


@pytest.fixture
def forager(theaters):
    return make_state(theaters, "forager_1944")


@pytest.fixture
def store():
    s = Store()
    yield s
    s.close()
