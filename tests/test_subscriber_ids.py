"""
Tests de la table d'identifiants opaques.

Remplace le SHA-256 non salé de l'adresse, qui se retournait par simple
comparaison avec la liste d'abonnés.

Deux propriétés critiques :
  - l'identifiant n'est pas dérivable de l'adresse
  - retirer une ligne de la table rend l'historique de mesures anonyme,
    ce qui est le mécanisme d'effacement sur demande
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.subscriber_ids import (
    SubscriberIds,
    build_ids_toml,
    parse_ids_toml,
)


@pytest.fixture
def store(tmp_path) -> SubscriberIds:
    return SubscriberIds(tmp_path / "subscriber_ids.toml")


# ── Attribution ──────────────────────────────────────────────────────────────

def test_a_new_address_receives_an_identifier(store):
    identifier = store.get_or_create("a@example.com")

    assert identifier
    assert len(identifier) >= 16


def test_the_same_address_always_receives_the_same_identifier(store):
    first = store.get_or_create("a@example.com")

    assert store.get_or_create("a@example.com") == first


def test_two_addresses_receive_different_identifiers(store):
    assert store.get_or_create("a@example.com") != store.get_or_create("b@example.com")


def test_the_address_is_normalised_before_lookup(store):
    first = store.get_or_create("a@example.com")

    assert store.get_or_create("  A@Example.COM ") == first


def test_the_identifier_is_not_derivable_from_the_address(store):
    """
    Le défaut d'origine : sha256(email) se retournait avec la liste d'abonnés.
    Un identifiant aléatoire n'a aucun lien calculable avec l'adresse.
    """
    import hashlib

    identifier = store.get_or_create("a@example.com")
    forbidden = {
        hashlib.sha256(b"a@example.com").hexdigest(),
        hashlib.md5(b"a@example.com").hexdigest(),
        hashlib.sha1(b"a@example.com").hexdigest(),
    }

    assert identifier not in forbidden
    assert not any(f.startswith(identifier) for f in forbidden)


def test_two_stores_give_different_identifiers_to_the_same_address(tmp_path):
    """Preuve que l'identifiant est tiré au sort et non calculé."""
    a = SubscriberIds(tmp_path / "a.toml").get_or_create("x@example.com")
    b = SubscriberIds(tmp_path / "b.toml").get_or_create("x@example.com")

    assert a != b


# ── Persistance ──────────────────────────────────────────────────────────────

def test_identifiers_survive_a_reload(tmp_path):
    path = tmp_path / "ids.toml"
    first = SubscriberIds(path).get_or_create("a@example.com")

    assert SubscriberIds(path).get_or_create("a@example.com") == first


def test_toml_round_trip(tmp_path):
    entries = {"a@example.com": "id-aaa", "b@example.com": "id-bbb"}

    assert parse_ids_toml(build_ids_toml(entries)) == entries


def test_an_absent_file_starts_empty(tmp_path):
    assert SubscriberIds(tmp_path / "nowhere.toml").all_ids() == {}


# ── Effacement ───────────────────────────────────────────────────────────────

def test_forgetting_an_address_removes_it_from_the_table(store):
    store.get_or_create("a@example.com")

    assert store.forget("a@example.com") is True
    assert "a@example.com" not in store.all_ids()


def test_forgetting_an_unknown_address_reports_nothing_to_do(store):
    assert store.forget("inconnu@example.com") is False


def test_after_forgetting_the_address_cannot_be_linked_to_its_history(store):
    """
    C'est le mécanisme d'effacement : les mesures gardent l'identifiant, mais
    plus rien ne permet de remonter à la personne.
    """
    identifier = store.get_or_create("a@example.com")
    store.forget("a@example.com")

    assert identifier not in store.all_ids().values()


def test_forgetting_then_resubscribing_yields_a_new_identifier(store):
    first = store.get_or_create("a@example.com")
    store.forget("a@example.com")

    assert store.get_or_create("a@example.com") != first
