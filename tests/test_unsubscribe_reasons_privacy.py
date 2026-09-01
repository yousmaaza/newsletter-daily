"""
Tests de la confidentialité du fichier des motifs de désinscription.

Constaté à l'audit : `data/unsubscribe_reasons.csv` stockait l'adresse email
EN CLAIR — contrairement à tous les autres fichiers de mesures — et le message
de commit la répétait, la gravant dans l'historique git.

Or `build_dashboard_data.py` ne lit que timestamp, reasons et free_text.
L'adresse ne servait à rien : la bonne réponse est de ne plus la collecter.
"""

import csv
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

import auth_server.unsubscribe as unsub

EMAIL = "partant@example.com"


class FakeGitHub:
    def __init__(self, initial: str = ""):
        self.content = initial
        self.messages: list[str] = []

    def put_with_retry(self, path, build, message, token, repo):
        self.content = build(self.content)
        self.messages.append(message)


@pytest.fixture
def github(monkeypatch) -> FakeGitHub:
    gh = FakeGitHub()
    monkeypatch.setattr(unsub, "_github_put_with_retry", gh.put_with_retry)
    return gh


def _write(github: FakeGitHub, free_text: str = "trop long"):
    unsub.append_reason_csv(EMAIL, "2026-08-25", ["too_long"], free_text, "tok", "u/r")
    return list(csv.DictReader(io.StringIO(github.content)))


# ── Le défaut d'origine ──────────────────────────────────────────────────────

def test_the_address_is_not_written_to_the_file(github):
    _write(github)

    assert EMAIL not in github.content


def test_the_address_is_not_written_to_the_commit_message(github):
    """Un message de commit est définitif : l'adresse y serait ineffaçable."""
    _write(github)

    assert all(EMAIL not in m for m in github.messages)
    assert all("@" not in m for m in github.messages)


def test_the_file_has_no_email_column(github):
    rows = _write(github)

    assert "email" not in rows[0]


# ── Ce qui doit rester ───────────────────────────────────────────────────────

def test_the_reason_is_kept(github):
    rows = _write(github)

    assert rows[0]["reasons"] == "too_long"


def test_the_free_text_is_kept(github):
    rows = _write(github)

    assert rows[0]["free_text"] == "trop long"


def test_the_send_date_is_kept(github):
    rows = _write(github)

    assert rows[0]["send_date"] == "2026-08-25"


def test_the_free_text_is_still_capped(github):
    rows = _write(github, free_text="x" * 900)

    assert len(rows[0]["free_text"]) == 500


def test_several_departures_accumulate(github):
    _write(github)
    rows = _write(github)

    assert len(rows) == 2


# ── Ce que le tableau de bord attend ─────────────────────────────────────────

def test_the_columns_the_dashboard_reads_are_present(github):
    """build_dashboard_data.py lit timestamp, reasons et free_text."""
    rows = _write(github)

    for column in ("timestamp", "reasons", "free_text"):
        assert column in rows[0]
