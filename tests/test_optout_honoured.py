"""
Tests du respect effectif du refus de mesure au moment de l'envoi.

Le bouton « ne plus être mesuré » ne vaut que si l'édition suivante en tient
compte. Et couper la mesure ne doit pas emporter le lien de désinscription.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.newsletter_renderer import render_for_recipient

NEWSLETTER = {
    "newsletter_title": "Le Brief",
    "intro": "Intro.",
    "conclusion": "Fin.",
    "articles": [
        {
            "rank": 1, "title": "Tornade", "flash": "Flash.", "detail": "Détail.",
            "topic": "monde", "hype": "viral",
            "sources": [{"title": "Figaro", "url": "https://lefigaro.fr/a", "source": "lefigaro.fr"}],
        }
    ],
}

AUTH = {"auth_server_url": "https://track.example.com", "secret": "s3cr3t"}


def _render(**kwargs):
    return render_for_recipient(NEWSLETTER, "a@example.com", "2026-08-25", **{**AUTH, **kwargs})


def test_an_opted_out_reader_gets_no_pixel():
    assert "/pixel" not in _render(tracking_enabled=False)


def test_an_opted_out_reader_gets_direct_source_links():
    html = _render(tracking_enabled=False)

    assert "https://lefigaro.fr/a" in html
    assert "/click?" not in html


def test_an_opted_out_reader_keeps_the_unsubscribe_link():
    """Couper la mesure ne doit jamais retirer le moyen de se désabonner."""
    assert "/unsubscribe?" in _render(tracking_enabled=False)


def test_a_measured_reader_still_gets_the_pixel():
    assert "/pixel" in _render(tracking_enabled=True)


def test_tracking_is_on_by_default():
    assert "/pixel" in _render()
