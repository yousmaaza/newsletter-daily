"""
Tests de l'exigence de configuration pour un envoi de test avec bloc.

Quand on demande explicitement le bloc, une config incomplète doit provoquer
une erreur nommant ce qui manque — pas un email silencieusement dépourvu du
bouton qu'on voulait justement tester.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.newsletter_renderer import require_transparency_notice

COMPLETE = {
    "auth_server_url": "https://track.example.com",
    "secret": "s3cr3t",
    "dashboard_url": "https://track.example.com/board",
}


def test_a_complete_configuration_yields_a_usable_notice():
    notice = require_transparency_notice("a@example.com", "2026-08-25", **COMPLETE)

    assert notice["dashboard_url"] == COMPLETE["dashboard_url"]
    assert "/tracking-optout?" in notice["tracking_optout_url"]
    assert notice["stats"]["total_editions"] >= 0


def test_a_missing_dashboard_url_is_named_in_the_error():
    with pytest.raises(ValueError, match="DASHBOARD_PUBLIC_URL"):
        require_transparency_notice(
            "a@example.com", "2026-08-25", **{**COMPLETE, "dashboard_url": ""}
        )


def test_a_missing_auth_server_is_named_in_the_error():
    with pytest.raises(ValueError, match="AUTH_SERVER_URL"):
        require_transparency_notice(
            "a@example.com", "2026-08-25", **{**COMPLETE, "auth_server_url": ""}
        )


def test_a_missing_secret_is_named_in_the_error():
    with pytest.raises(ValueError, match="UNSUBSCRIBE_SECRET"):
        require_transparency_notice("a@example.com", "2026-08-25", **{**COMPLETE, "secret": ""})


def test_every_missing_item_is_listed_at_once():
    """Ne pas faire découvrir les manques un par un, à chaque tentative."""
    with pytest.raises(ValueError) as exc:
        require_transparency_notice("a@example.com", "2026-08-25",
                                    auth_server_url="", secret="", dashboard_url="")

    message = str(exc.value)
    assert "AUTH_SERVER_URL" in message
    assert "UNSUBSCRIBE_SECRET" in message
    assert "DASHBOARD_PUBLIC_URL" in message


def test_the_optout_link_points_at_the_configured_server():
    """Le lien doit viser le serveur déployé, sinon le clic ne teste rien."""
    notice = require_transparency_notice("a@example.com", "2026-08-25", **COMPLETE)

    assert notice["tracking_optout_url"].startswith("https://track.example.com/tracking-optout")
