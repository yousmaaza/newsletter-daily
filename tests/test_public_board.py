"""
Tests du tableau de bord public /board.

Propriété critique : le filtrage est une **liste blanche**. Toute clé ajoutée
plus tard au payload du dashboard privé est exclue par défaut — la
confidentialité ne doit pas reposer sur le fait que personne n'enrichira jamais
`build_dashboard_data.py`.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

from auth_server.public_board import PUBLIC_KEYS, public_payload

FULL_PAYLOAD = {
    "generated": "2026-08-25T19:18:30+00:00",
    "editions": [
        {"date": "2026-08-25", "opens": 17, "clickers": 4,
         "comments": ["Pas assez d'articles de finances ou en lien avec la bourse"]},
        {"date": "2026-08-24", "opens": 13, "clickers": 2, "comments": []},
    ],
    "current_sent": 25,
    "unique_readers": 26,
    "by_rank": {"1": 12, "2": 8},
    "by_domain": {"lefigaro.fr": 9},
    "by_hour": {"06": 14},
    "loyalty": [100, 99, 3, 1],
    "unsub": [
        {"date": "2026-04-01", "reason": "too_frequent", "text": "trop de mails de Yousri"},
        {"date": "2026-05-02", "reason": "too_long", "text": ""},
    ],
    "unsub_reasons": {"too_frequent": 3},
    "topics": {"monde": 31},
    "totals": {"opens": 1706, "clicks": 168},
    "live": True,
    "runs": [{"date": "2026-08-25", "ok": True,
              "url": "https://github.com/yousmaaza/newletter-ai/actions/runs/1"}],
}


def test_the_aggregate_metrics_are_published():
    result = public_payload(FULL_PAYLOAD)

    for key in ("editions", "totals", "by_rank", "by_domain", "by_hour", "loyalty", "unique_readers"):
        assert key in result


def test_an_unknown_key_is_excluded_by_default():
    """C'est la garantie de la liste blanche : ce qui n'est pas prévu ne sort pas."""
    enriched = {**FULL_PAYLOAD, "per_reader_detail": {"abc123": ["2026-08-25"]}}

    assert "per_reader_detail" not in public_payload(enriched)


def test_a_future_sensitive_key_does_not_leak():
    enriched = {**FULL_PAYLOAD, "email_hashes": ["4d8323e4ff8ba2f2"], "subscribers": ["a@b.com"]}
    result = public_payload(enriched)

    assert "email_hashes" not in result
    assert "subscribers" not in result


NEUTRALISED = {"runs", "live", "unsub"}


def test_nothing_beyond_the_whitelist_and_the_neutralised_keys_comes_out():
    assert set(public_payload(FULL_PAYLOAD)) <= set(PUBLIC_KEYS) | NEUTRALISED


def test_a_missing_whitelisted_key_is_simply_absent():
    result = public_payload({"editions": [], "runs": []})

    assert result["editions"] == []
    assert "totals" not in result          # absent du payload source → absent ici


def test_an_empty_payload_still_yields_the_keys_the_page_needs():
    result = public_payload({})

    assert result == {"runs": [], "live": False, "unsub": []}


def test_runs_keeps_its_entries():
    """
    Vider `runs` casse la page autrement : elle fait `runs[runs.length-1].ok`
    pour la bannière, et divise par `runs.length` pour le taux de réussite.
    Seule l'URL doit disparaître.
    """
    result = public_payload(FULL_PAYLOAD)

    assert len(result["runs"]) == len(FULL_PAYLOAD["runs"])


def test_runs_entries_keep_the_fields_the_page_reads():
    """dashboard.html lit r.ok et r.date, jamais r.url."""
    entry = public_payload(FULL_PAYLOAD)["runs"][0]

    assert entry["ok"] is True
    assert entry["date"] == "2026-08-25"


def test_runs_entries_lose_the_github_url():
    entry = public_payload(FULL_PAYLOAD)["runs"][0]

    assert "url" not in entry


def test_no_github_url_survives_in_runs():
    body = str(public_payload(FULL_PAYLOAD))

    assert "github.com" not in body
    assert "yousmaaza" not in body


def test_live_is_forced_off_on_the_public_board():
    """Le public board est mis en cache 300 s : pas d'auto-rafraîchissement."""
    assert public_payload(FULL_PAYLOAD)["live"] is False


def test_unsubscribe_entries_keep_their_date_and_reason():
    result = public_payload(FULL_PAYLOAD)

    assert len(result["unsub"]) == 2
    assert result["unsub"][0]["reason"] == "too_frequent"
    assert result["unsub"][0]["date"] == "2026-04-01"


def test_reader_comments_are_never_published():
    """
    Les commentaires laissés en bas d'édition sont écrits pour l'auteur de la
    newsletter, pas pour le public. Sur 26 lecteurs, une phrase reconnaissable
    suffit à identifier son auteur.
    """
    result = public_payload(FULL_PAYLOAD)

    assert all(edition["comments"] == [] for edition in result["editions"])
    assert "Pas assez d'articles de finances" not in str(result)


def test_editions_keep_their_comments_key():
    """dashboard.html fait `e.comments.map(...)` : la clé absente plante la page."""
    for edition in public_payload(FULL_PAYLOAD)["editions"]:
        assert "comments" in edition


def test_editions_keep_their_metrics():
    edition = public_payload(FULL_PAYLOAD)["editions"][0]

    assert edition["opens"] == 17
    assert edition["clickers"] == 4
    assert edition["date"] == "2026-08-25"


def test_the_free_text_written_when_leaving_is_never_published():
    """Ce que quelqu'un écrit en partant lui appartient."""
    result = public_payload(FULL_PAYLOAD)

    assert all("text" not in entry for entry in result["unsub"])
    assert "trop de mails de Yousri" not in str(result)


def test_a_malformed_unsub_entry_does_not_crash_the_filter():
    result = public_payload({**FULL_PAYLOAD, "unsub": ["pas un dict", {"reason": "x"}]})

    assert len(result["unsub"]) == 2
