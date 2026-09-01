"""
Tests de l'écriture GitHub lors d'un refus de mesure.

Constaté en production : deux clics sur le même lien ont produit deux commits,
dont le second vide. `apply_optout` est bien idempotent sur le contenu, mais le
PUT partait quand même — et l'API GitHub crée un commit même à contenu
identique. Un préchargeur de liens d'un client mail suffirait à polluer
l'historique de main.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

import auth_server.tracking_optout as mod


class FakeGitHub:
    """Capture les écritures au lieu de les envoyer."""

    def __init__(self, initial: str = ""):
        self.content = initial
        self.writes: list[str] = []

    def put_with_retry(self, path, build, message, token, repo):
        new_content = build(self.content)
        if new_content == self.content:
            # comportement attendu après correctif : l'appelant n'écrit pas
            raise AssertionError("PUT appelé alors que le contenu est inchangé")
        self.content = new_content
        self.writes.append(message)


def _install(monkeypatch, github: FakeGitHub):
    monkeypatch.setattr(mod, "_github_put_with_retry", github.put_with_retry)
    monkeypatch.setattr(mod, "_github_get_file", lambda p, t, r: (None, github.content))


def test_a_first_optout_writes_once(monkeypatch):
    gh = FakeGitHub()
    _install(monkeypatch, gh)

    added = mod.add_to_tracking_optout("a@example.com", "tok", "u/r")

    assert added is True
    assert len(gh.writes) == 1
    assert "a@example.com" in gh.content


def test_a_second_click_writes_nothing(monkeypatch):
    """Le cas qui a produit un commit vide sur main."""
    gh = FakeGitHub()
    _install(monkeypatch, gh)
    mod.add_to_tracking_optout("a@example.com", "tok", "u/r")

    added = mod.add_to_tracking_optout("a@example.com", "tok", "u/r")

    assert added is False
    assert len(gh.writes) == 1, "un second commit a été créé pour rien"


def test_a_second_click_in_another_case_writes_nothing(monkeypatch):
    gh = FakeGitHub()
    _install(monkeypatch, gh)
    mod.add_to_tracking_optout("a@example.com", "tok", "u/r")

    added = mod.add_to_tracking_optout("  A@EXAMPLE.COM  ", "tok", "u/r")

    assert added is False
    assert len(gh.writes) == 1


def test_a_different_address_still_writes(monkeypatch):
    gh = FakeGitHub()
    _install(monkeypatch, gh)
    mod.add_to_tracking_optout("a@example.com", "tok", "u/r")

    added = mod.add_to_tracking_optout("b@example.com", "tok", "u/r")

    assert added is True
    assert len(gh.writes) == 2
    assert "b@example.com" in gh.content
