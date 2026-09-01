"""
Tests de l'identifiant porté par les URL d'interaction.

C'est ici que le défaut d'origine vivait : `sha256(email)` non salé, présent
dans les quatre constructeurs d'URL et donc recopié dans tous les CSV.
"""

import hashlib
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.interaction_helper as helper
from tools.subscriber_ids import SubscriberIds

SECRET = "s3cr3t"
BASE = "https://track.example.com"
EMAIL = "lecteur@example.com"
DATE = "2026-08-25"


@pytest.fixture
def store(tmp_path, monkeypatch) -> SubscriberIds:
    ids = SubscriberIds(tmp_path / "ids.toml")
    monkeypatch.setattr(helper, "_subscriber_ids", lambda: ids)
    return ids


def _identifier_in(url: str) -> str:
    return parse_qs(urlparse(url).query)["email"][0]


ALL_BUILDERS = [
    ("pixel",    lambda: helper.build_pixel_url(BASE, EMAIL, DATE, SECRET)),
    ("click",    lambda: helper.build_click_url(BASE, EMAIL, DATE, 1, "https://x.fr", SECRET)),
    ("reaction", lambda: helper.build_reaction_url(BASE, EMAIL, DATE, 1, "like", SECRET)),
    ("feedback", lambda: helper.build_feedback_url(BASE, EMAIL, DATE, "like", SECRET)),
]


@pytest.mark.parametrize("name,build", ALL_BUILDERS, ids=[n for n, _ in ALL_BUILDERS])
def test_no_builder_leaks_the_reversible_hash(name, build, store):
    """Le défaut d'origine : l'adresse hachée sans sel, retournable."""
    reversible = hashlib.sha256(EMAIL.encode()).hexdigest()

    assert reversible not in build()


@pytest.mark.parametrize("name,build", ALL_BUILDERS, ids=[n for n, _ in ALL_BUILDERS])
def test_every_builder_uses_the_opaque_identifier(name, build, store):
    expected = store.get_or_create(EMAIL)

    assert _identifier_in(build()) == expected


def test_no_builder_leaks_the_address_itself(store):
    for _, build in ALL_BUILDERS:
        assert EMAIL not in build()


def test_the_four_builders_agree_on_the_identifier(store):
    identifiers = {_identifier_in(build()) for _, build in ALL_BUILDERS}

    assert len(identifiers) == 1


def test_a_new_subscriber_is_registered_on_first_send(store):
    assert store.get("nouveau@example.com") is None

    helper.build_pixel_url(BASE, "nouveau@example.com", DATE, SECRET)

    assert store.get("nouveau@example.com") is not None


def test_two_subscribers_get_different_identifiers(store):
    a = _identifier_in(helper.build_pixel_url(BASE, "a@example.com", DATE, SECRET))
    b = _identifier_in(helper.build_pixel_url(BASE, "b@example.com", DATE, SECRET))

    assert a != b


def test_the_signature_still_covers_the_identifier(store):
    """Le jeton HMAC doit rester vérifiable : il signe l'identifiant transmis."""
    url = helper.build_pixel_url(BASE, EMAIL, DATE, SECRET)
    params = parse_qs(urlparse(url).query)

    expected = helper._make_token(SECRET, params["email"][0], DATE)
    assert params["token"][0] == expected
