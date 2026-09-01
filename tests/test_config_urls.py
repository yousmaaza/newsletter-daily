"""
Tests de normalisation des URL de configuration.

En CI, DASHBOARD_PUBLIC_URL et PRIVACY_URL sont dérivées d'AUTH_SERVER_URL.
Si ce secret porte un slash final, la concaténation produit `//board`, que
Flask renvoie en 404 — un lien mort dans le bloc transparence.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _reload_config(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config as config_module
    importlib.reload(config_module)
    return config_module.config


def test_a_trailing_slash_is_stripped_from_the_dashboard_url(monkeypatch):
    cfg = _reload_config(monkeypatch, DASHBOARD_PUBLIC_URL="https://x.app//board")

    assert cfg.DASHBOARD_PUBLIC_URL == "https://x.app/board"


def test_a_trailing_slash_is_stripped_from_the_privacy_url(monkeypatch):
    cfg = _reload_config(monkeypatch, PRIVACY_URL="https://x.app/vie-privee/")

    assert cfg.PRIVACY_URL == "https://x.app/vie-privee"


def test_a_clean_url_is_left_alone(monkeypatch):
    cfg = _reload_config(monkeypatch, DASHBOARD_PUBLIC_URL="https://x.app/board")

    assert cfg.DASHBOARD_PUBLIC_URL == "https://x.app/board"


def test_an_empty_url_stays_empty(monkeypatch):
    """Sans page vie privée, la ligne du bloc disparaît — elle ne doit pas
    devenir un lien vide."""
    cfg = _reload_config(monkeypatch, PRIVACY_URL="")

    assert cfg.PRIVACY_URL == ""
