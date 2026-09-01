"""
Tests du lien signé « ne plus être mesuré ».

Propriété de sécurité : le jeton d'opt-out ne doit pas être interchangeable
avec celui de désinscription. Sinon un lien capté dans un email permettrait
de déclencher l'autre action sur le même abonné.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.unsubscribe_helper import (
    build_tracking_optout_url,
    build_unsubscribe_url,
    generate_optout_token,
    generate_token,
)

SECRET = "s3cr3t"


def test_optout_url_targets_the_tracking_optout_route():
    url = build_tracking_optout_url("https://track.example.com", "a@example.com", "2026-08-25", SECRET)

    assert urlparse(url).path == "/tracking-optout"


def test_optout_url_carries_email_date_and_token():
    url = build_tracking_optout_url("https://track.example.com", "a@example.com", "2026-08-25", SECRET)
    params = parse_qs(urlparse(url).query)

    assert params["email"] == ["a@example.com"]
    assert params["date"] == ["2026-08-25"]
    assert len(params["token"][0]) == 64


def test_optout_token_differs_from_the_unsubscribe_token():
    """Les deux actions sont distinctes : leurs jetons ne doivent pas coïncider."""
    optout = generate_optout_token("a@example.com", "2026-08-25", SECRET)
    unsub = generate_token("a@example.com", "2026-08-25", SECRET)

    assert optout != unsub


def test_an_unsubscribe_link_cannot_be_replayed_as_an_optout():
    unsub_token = parse_qs(urlparse(
        build_unsubscribe_url("https://t.example.com", "a@example.com", "2026-08-25", SECRET)
    ).query)["token"][0]

    assert unsub_token != generate_optout_token("a@example.com", "2026-08-25", SECRET)


def test_optout_token_is_specific_to_the_subscriber():
    assert (
        generate_optout_token("a@example.com", "2026-08-25", SECRET)
        != generate_optout_token("b@example.com", "2026-08-25", SECRET)
    )


def test_optout_token_is_case_insensitive_on_the_address():
    assert (
        generate_optout_token("A@Example.COM", "2026-08-25", SECRET)
        == generate_optout_token("a@example.com", "2026-08-25", SECRET)
    )
