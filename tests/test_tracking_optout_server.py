"""
Tests côté serveur du refus de mesure.

Deux propriétés critiques :
  - un jeton de désinscription ne doit pas ouvrir le refus de mesure
  - l'ajout à la liste doit être idempotent (un lien cliqué deux fois, un
    préchargeur d'email qui suit le lien... rien ne doit dupliquer ni casser)
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "auth_server"))

from auth_server.tracking_optout import (
    apply_optout,
    build_optout_toml,
    generate_optout_token,
    parse_optout_toml,
    verify_optout_token,
)
from auth_server.unsubscribe import generate_token as generate_unsub_token

SECRET = "s3cr3t"
TODAY = date.today().strftime("%Y-%m-%d")


# ── Jeton ────────────────────────────────────────────────────────────────────

def test_a_valid_token_is_accepted():
    token = generate_optout_token("a@example.com", TODAY, SECRET)

    assert verify_optout_token("a@example.com", TODAY, token, SECRET)


def test_an_unsubscribe_token_does_not_open_the_optout():
    """Refuser la mesure et se désabonner sont deux actions distinctes."""
    unsub = generate_unsub_token("a@example.com", TODAY, SECRET)

    assert not verify_optout_token("a@example.com", TODAY, unsub, SECRET)


def test_a_token_for_another_address_is_rejected():
    token = generate_optout_token("a@example.com", TODAY, SECRET)

    assert not verify_optout_token("b@example.com", TODAY, token, SECRET)


def test_a_tampered_token_is_rejected():
    token = generate_optout_token("a@example.com", TODAY, SECRET)
    tampered = ("0" if token[0] != "0" else "1") + token[1:]

    assert not verify_optout_token("a@example.com", TODAY, tampered, SECRET)


def test_a_link_older_than_ninety_days_is_rejected():
    old = (date.today() - timedelta(days=91)).strftime("%Y-%m-%d")
    token = generate_optout_token("a@example.com", old, SECRET)

    assert not verify_optout_token("a@example.com", old, token, SECRET)


def test_missing_parameters_are_rejected():
    assert not verify_optout_token("", TODAY, "x", SECRET)
    assert not verify_optout_token("a@example.com", "", "x", SECRET)
    assert not verify_optout_token("a@example.com", TODAY, "", SECRET)
    assert not verify_optout_token("a@example.com", "pas-une-date", "x", SECRET)


# ── Stockage TOML ────────────────────────────────────────────────────────────

def test_toml_round_trip_preserves_addresses_and_timestamps():
    entries = {"a@example.com": "2026-08-25T10:00:00Z", "b@example.com": "2026-08-26T11:00:00Z"}

    assert parse_optout_toml(build_optout_toml(entries)) == entries


def test_an_empty_file_parses_as_no_optout():
    assert parse_optout_toml("") == {}
    assert parse_optout_toml("[tracking_optout]\nemails = []\ntimestamps = []\n") == {}


def test_applying_the_optout_adds_the_address():
    updated, was_new = apply_optout("", "a@example.com", "2026-08-25T10:00:00Z")

    assert was_new is True
    assert "a@example.com" in parse_optout_toml(updated)


def test_applying_twice_is_idempotent():
    once, _ = apply_optout("", "a@example.com", "2026-08-25T10:00:00Z")
    twice, was_new = apply_optout(once, "a@example.com", "2026-08-26T09:00:00Z")

    assert was_new is False
    assert twice == once                       # contenu inchangé → aucun commit inutile
    assert len(parse_optout_toml(twice)) == 1


def test_the_address_is_normalised_before_storage():
    updated, _ = apply_optout("", "  A@Example.COM ", "2026-08-25T10:00:00Z")

    assert "a@example.com" in parse_optout_toml(updated)


def test_an_existing_address_in_another_case_is_recognised():
    once, _ = apply_optout("", "a@example.com", "2026-08-25T10:00:00Z")
    _, was_new = apply_optout(once, "A@EXAMPLE.COM", "2026-08-26T09:00:00Z")

    assert was_new is False
