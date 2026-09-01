"""
Tests du routage vers le dépôt de données (#55).

Les fichiers de `config/` portent des adresses et vivent dans le dépôt privé.
Ceux de `data/` sont anonymes depuis la migration et restent dans le dépôt
applicatif. Une confusion entre les deux republierait des adresses.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))


@pytest.fixture
def flask_app(monkeypatch):
    monkeypatch.setenv("GITHUB_REPO", "user/app")
    import app as flask_app
    return flask_app


def test_the_data_repo_is_used_when_defined(flask_app, monkeypatch):
    monkeypatch.setenv("DATA_REPO", "user/data")

    assert flask_app._data_repo() == "user/data"


def test_it_falls_back_on_the_application_repo(flask_app, monkeypatch):
    """Repli pendant la transition : rien ne casse si DATA_REPO n'est pas posé."""
    monkeypatch.delenv("DATA_REPO", raising=False)

    assert flask_app._data_repo() == "user/app"


def test_an_empty_data_repo_falls_back_too(flask_app, monkeypatch):
    monkeypatch.setenv("DATA_REPO", "")

    assert flask_app._data_repo() == "user/app"
