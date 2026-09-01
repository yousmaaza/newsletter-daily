"""
Tests de l'écriture GitHub lors d'une désinscription — ticket #52.

Même défaut que celui corrigé pour /tracking-optout dans 3117cab : la
fonction `build` renvoie bien le contenu inchangé quand l'adresse est déjà
présente, mais le PUT part quand même — et l'API GitHub Contents crée un
commit même à contenu identique.

Le déclencheur n'est pas le double clic humain mais le préchargeur de liens
de certains clients mail, qui suit les URL sans intervention. Chaque édition
envoyée pouvait donc produire des commits vides sur main.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

import auth_server.unsubscribe as unsub


class FakeGitHub:
    """Capture les écritures, et refuse un PUT à contenu inchangé."""

    def __init__(self, initial: str = ""):
        self.content = initial
        self.writes: list[str] = []

    def put_with_retry(self, path, build, message, token, repo):
        new_content = build(self.content)
        if new_content == self.content:
            raise AssertionError("PUT appelé alors que le contenu est inchangé")
        self.content = new_content
        self.writes.append(message)


@pytest.fixture
def github(monkeypatch) -> FakeGitHub:
    gh = FakeGitHub()
    monkeypatch.setattr(unsub, "_github_put_with_retry", gh.put_with_retry)
    monkeypatch.setattr(unsub, "_github_get_file", lambda p, t, r: (None, gh.content))
    return gh


# ── Le défaut ────────────────────────────────────────────────────────────────

def test_a_first_unsubscribe_writes_once(github):
    added = unsub.add_to_unsubscribed("a@example.com", "tok", "u/r")

    assert added is True
    assert len(github.writes) == 1
    assert "a@example.com" in github.content


def test_a_second_click_writes_nothing(github):
    """Le cas qui produisait un commit vide."""
    unsub.add_to_unsubscribed("a@example.com", "tok", "u/r")

    added = unsub.add_to_unsubscribed("a@example.com", "tok", "u/r")

    assert added is False
    assert len(github.writes) == 1, "un second commit a été créé pour rien"


def test_a_second_click_in_another_case_writes_nothing(github):
    unsub.add_to_unsubscribed("a@example.com", "tok", "u/r")

    added = unsub.add_to_unsubscribed("  A@EXAMPLE.COM  ", "tok", "u/r")

    assert added is False
    assert len(github.writes) == 1


def test_a_different_address_still_writes(github):
    unsub.add_to_unsubscribed("a@example.com", "tok", "u/r")

    added = unsub.add_to_unsubscribed("b@example.com", "tok", "u/r")

    assert added is True
    assert len(github.writes) == 2
    assert "b@example.com" in github.content


# ── Ce qui doit rester vrai ──────────────────────────────────────────────────

def test_the_timestamp_is_recorded(github):
    unsub.add_to_unsubscribed("a@example.com", "tok", "u/r")
    entries = unsub._parse_unsubscribed_toml(github.content)

    assert entries["a@example.com"].endswith("Z")


def test_the_existing_entries_are_preserved(github):
    unsub.add_to_unsubscribed("a@example.com", "tok", "u/r")
    unsub.add_to_unsubscribed("b@example.com", "tok", "u/r")

    assert set(unsub._parse_unsubscribed_toml(github.content)) == {
        "a@example.com", "b@example.com"
    }
