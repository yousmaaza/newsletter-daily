"""
Tests de l'enregistrement des interactions.

Deux défauts traités ensemble, tous deux constatés en production :

1. Les anciens hashs réversibles réapparaissaient. Les éditions déjà
   distribuées portent l'ancien identifiant dans leurs URL ; chaque ouverture
   d'une ancienne édition en réintroduisait un.

2. Commits vides — 15 sur 28 pour la seule journée du 26 août. `save_open` est
   idempotent sur le contenu mais appelait le PUT quand même, et l'API GitHub
   crée un commit à contenu identique. C'est le même défaut que #52, sur
   l'endpoint le plus sollicité.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

import auth_server.interactions as inter

OPAQUE = "a3f1" * 8       # 32 hex
OTHER = "c7d9" * 8
LEGACY = "b7c2" * 16      # 64 hex — ancien SHA-256


class FakeGitHub:
    def __init__(self):
        self.files: dict[str, str] = {}
        self.writes: list[str] = []

    def put_with_retry(self, path, build, message, token, repo):
        current = self.files.get(path, "")
        new = build(current)
        if new == current:
            raise AssertionError(f"PUT sur {path} alors que le contenu est inchangé")
        self.files[path] = new
        self.writes.append(message)

    def get_file(self, path, token, repo):
        return None, self.files.get(path, "")


@pytest.fixture
def github(monkeypatch) -> FakeGitHub:
    gh = FakeGitHub()
    monkeypatch.setattr(inter, "_github_put_with_retry", gh.put_with_retry)
    monkeypatch.setattr(inter, "_github_get_file", gh.get_file)
    return gh


def _opens(github: FakeGitHub) -> str:
    return github.files.get("data/opens_2026-08-26.csv", "")


# ── Anciens identifiants ─────────────────────────────────────────────────────

def test_a_legacy_hash_is_not_recorded_as_is(github):
    inter.save_open(LEGACY, "2026-08-26", "tok", "u/r")

    assert LEGACY not in _opens(github)


def test_a_legacy_hash_becomes_the_anonymous_marker(github):
    inter.save_open(LEGACY, "2026-08-26", "tok", "u/r")

    assert "legacy" in _opens(github)


def test_the_row_is_still_recorded(github):
    """Les volumes publiés sur /board doivent rester justes."""
    inter.save_open(LEGACY, "2026-08-26", "tok", "u/r")

    assert "2026-08-26" in _opens(github)
    assert len(github.writes) == 1


def test_an_opaque_identifier_is_recorded_unchanged(github):
    inter.save_open(OPAQUE, "2026-08-26", "tok", "u/r")

    assert OPAQUE in _opens(github)


# ── Commits vides ────────────────────────────────────────────────────────────

def test_a_first_open_writes_once(github):
    inter.save_open(OPAQUE, "2026-08-26", "tok", "u/r")

    assert len(github.writes) == 1


def test_a_repeated_open_writes_nothing(github):
    """Le cas qui produisait 15 commits vides en une journée."""
    inter.save_open(OPAQUE, "2026-08-26", "tok", "u/r")

    inter.save_open(OPAQUE, "2026-08-26", "tok", "u/r")

    assert len(github.writes) == 1, "un commit vide a été créé"


def test_two_readers_both_write(github):
    inter.save_open(OPAQUE, "2026-08-26", "tok", "u/r")
    inter.save_open(OTHER, "2026-08-26", "tok", "u/r")

    assert len(github.writes) == 2


def test_two_legacy_opens_collapse_into_one_row(github):
    """Deux anciens identifiants deviennent le même marqueur : une seule ligne."""
    inter.save_open(LEGACY, "2026-08-26", "tok", "u/r")
    inter.save_open("d4e5" * 16, "2026-08-26", "tok", "u/r")

    assert len(github.writes) == 1
