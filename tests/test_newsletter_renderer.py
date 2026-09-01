"""
Tests du rendu newsletter extrait d'agent.py.

Le rendu était jusqu'ici enfermé dans une closure de `_handle_tool_use`, donc
impossible à prévisualiser sans lancer le pipeline complet et envoyer les emails.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.newsletter_renderer import render_for_recipient


@pytest.fixture
def newsletter_data() -> dict:
    return {
        "subject": "Le Brief du jour",
        "newsletter_title": "Le Brief du Mardi",
        "intro": "Trois infos ce matin.",
        "conclusion": "À demain.",
        "articles": [
            {
                "rank": 1,
                "title": "Tornade dans l'Aude",
                "flash": "Quarante-et-un blessés.",
                "detail": "Le phénomène s'est abattu sur Pomas.",
                "topic": "monde",
                "hype": "viral",
                "sources": [
                    {"title": "Le Figaro", "url": "https://lefigaro.fr/a", "source": "lefigaro.fr"}
                ],
            }
        ],
    }


TRACKING = {"auth_server_url": "https://track.example.com", "secret": "s3cr3t"}


def test_rendered_html_contains_the_article_title(newsletter_data):
    html = render_for_recipient(newsletter_data, "lecteur@example.com", "2026-08-25")

    assert "Tornade dans l'Aude" in html


def test_two_recipients_get_different_tracking_urls(newsletter_data):
    alice = render_for_recipient(newsletter_data, "alice@example.com", "2026-08-25", **TRACKING)
    bob = render_for_recipient(newsletter_data, "bob@example.com", "2026-08-25", **TRACKING)

    assert "track.example.com/pixel" in alice
    assert "track.example.com/pixel" in bob
    assert alice != bob


def test_render_without_tracking_omits_the_pixel(newsletter_data):
    html = render_for_recipient(newsletter_data, "lecteur@example.com", "2026-08-25")

    assert "/pixel" not in html


def test_render_without_tracking_links_sources_directly(newsletter_data):
    html = render_for_recipient(newsletter_data, "lecteur@example.com", "2026-08-25")

    assert "https://lefigaro.fr/a" in html
    assert "/click?" not in html


def test_send_date_is_rendered_as_a_french_label(newsletter_data):
    html = render_for_recipient(newsletter_data, "lecteur@example.com", "2026-08-25")

    assert "mardi 25 août 2026" in html
