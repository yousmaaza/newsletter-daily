"""
Tests du bloc transparence dans la newsletter rendue.

Propriété critique : le bloc ne doit JAMAIS s'afficher avec un lien mort.
Un encart « voici comment refuser » dont le bouton ne mène nulle part fait
plus de dégâts que pas d'encart du tout.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.newsletter_renderer import render_for_recipient

NEWSLETTER = {
    "subject": "Le Brief",
    "newsletter_title": "Le Brief du Mardi",
    "intro": "Trois infos.",
    "conclusion": "À demain.",
    "articles": [
        {
            "rank": 1, "title": "Tornade dans l'Aude", "flash": "Flash.",
            "detail": "Détail.", "topic": "monde", "hype": "viral",
            "sources": [{"title": "Figaro", "url": "https://lefigaro.fr/a", "source": "lefigaro.fr"}],
        }
    ],
}

STATS = {
    "total_editions": 101,
    "unique_readers": 26,
    "open_rate_pct": 68,
    "click_trend": [
        {"month": "2026-07", "label": "Juil.", "value": 2.5, "display": "2,5", "height": 50, "color": "#c9001e"},
        {"month": "2026-08", "label": "Août", "value": 3.4, "display": "3,4", "height": 68, "color": "#c9001e"},
    ],
}

LINKS = {
    "tracking_optout_url": "https://track.example.com/tracking-optout?e=x",
    "dashboard_url": "https://track.example.com/board",
    "privacy_url": "https://daily.example.com/vie-privee",
}


def _render(**notice):
    return render_for_recipient(
        NEWSLETTER, "lecteur@example.com", "2026-08-25", transparency_notice=notice or None
    )


def test_block_is_absent_when_no_notice_is_requested():
    assert "Ce que je mesure" not in _render()


def test_block_appears_with_stats_and_links():
    html = _render(stats=STATS, **LINKS)

    assert "Ce que je mesure" in html
    assert "101" in html
    assert "68" in html
    assert LINKS["tracking_optout_url"] in html
    assert LINKS["dashboard_url"] in html


def test_block_is_suppressed_when_the_optout_link_is_missing():
    html = _render(stats=STATS, dashboard_url=LINKS["dashboard_url"], privacy_url=LINKS["privacy_url"])

    assert "Ce que je mesure" not in html


def test_block_is_suppressed_when_the_dashboard_link_is_missing():
    html = _render(stats=STATS, tracking_optout_url=LINKS["tracking_optout_url"], privacy_url=LINKS["privacy_url"])

    assert "Ce que je mesure" not in html


def test_block_is_suppressed_when_there_are_no_stats():
    html = _render(**LINKS)

    assert "Ce que je mesure" not in html


def test_click_trend_bars_are_rendered_with_their_height():
    html = _render(stats=STATS, **LINKS)

    assert "height:68px" in html
    assert "height:50px" in html
    assert "Août" in html


def test_decimal_values_use_the_french_separator():
    html = _render(stats=STATS, **LINKS)

    assert "3,4" in html
    assert "3.4" not in html
