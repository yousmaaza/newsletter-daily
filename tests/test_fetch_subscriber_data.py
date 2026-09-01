"""
Tests de la récupération des données d'abonnés depuis le dépôt privé (#55).

Propriété critique : **ne jamais produire une liste vide ou partielle en
silence**. Une lecture qui échoue doit interrompre le processus, pas laisser
l'envoi partir à zéro destinataire ni réinscrire des désabonnés.

C'est le défaut exact de sync_recipients.gs, qui retourne `[]` sur une
réponse non-200 et écrit quand même.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.fetch_subscriber_data import SUBSCRIBER_FILES, fetch_subscriber_data

RECIPIENTS = '[recipients]\nemails = ["a@example.com", "b@example.com"]\n'
UNSUBSCRIBED = '[unsubscribed]\nemails = ["c@example.com"]\ntimestamps = ["2026-01-01T00:00:00Z"]\n'
IDS = '[subscriber_ids]\nemails = ["a@example.com"]\nids    = ["abc123"]\n'
OPTOUT = '[tracking_optout]\nemails = []\ntimestamps = []\n'

COMPLETE = {
    "config/recipients.toml": RECIPIENTS,
    "config/unsubscribed.toml": UNSUBSCRIBED,
    "config/subscriber_ids.toml": IDS,
    "config/tracking_optout.toml": OPTOUT,
}


def _fetcher(files: dict):
    """Faux téléchargeur : retourne le contenu, ou None si absent."""
    def fetch(path: str) -> str | None:
        return files.get(path)
    return fetch


# ── Cas nominal ──────────────────────────────────────────────────────────────

def test_the_three_files_are_written(tmp_path):
    fetch_subscriber_data(tmp_path, fetch=_fetcher(COMPLETE))

    for path in SUBSCRIBER_FILES:
        assert (tmp_path / Path(path).name).exists()


def test_the_content_is_written_verbatim(tmp_path):
    fetch_subscriber_data(tmp_path, fetch=_fetcher(COMPLETE))

    assert (tmp_path / "recipients.toml").read_text(encoding="utf-8") == RECIPIENTS


def test_the_report_counts_the_entries(tmp_path):
    report = fetch_subscriber_data(tmp_path, fetch=_fetcher(COMPLETE))

    assert report["config/recipients.toml"] == 2
    assert report["config/unsubscribed.toml"] == 1


# ── Échecs : bruyants, jamais silencieux ─────────────────────────────────────

def test_an_unreachable_repository_raises(tmp_path):
    def fetch(path):
        raise ConnectionError("dépôt injoignable")

    with pytest.raises(ConnectionError):
        fetch_subscriber_data(tmp_path, fetch=fetch)


def test_a_missing_file_raises_and_names_it(tmp_path):
    partial = dict(COMPLETE)
    del partial["config/unsubscribed.toml"]

    with pytest.raises(RuntimeError, match="unsubscribed.toml"):
        fetch_subscriber_data(tmp_path, fetch=_fetcher(partial))


def test_an_empty_recipients_file_raises(tmp_path):
    """Une liste vide est plus probablement un échec qu'un état réel."""
    broken = {**COMPLETE, "config/recipients.toml": '[recipients]\nemails = []\n'}

    with pytest.raises(RuntimeError, match="aucun destinataire"):
        fetch_subscriber_data(tmp_path, fetch=_fetcher(broken))


def test_an_unparsable_file_raises(tmp_path):
    broken = {**COMPLETE, "config/recipients.toml": "ceci n'est pas du TOML ["}

    with pytest.raises(RuntimeError, match="illisible"):
        fetch_subscriber_data(tmp_path, fetch=_fetcher(broken))


def test_nothing_is_written_when_a_file_is_missing(tmp_path):
    """Tout ou rien : un config/ à moitié écrit est pire qu'un échec net."""
    partial = dict(COMPLETE)
    del partial["config/subscriber_ids.toml"]

    with pytest.raises(RuntimeError):
        fetch_subscriber_data(tmp_path, fetch=_fetcher(partial))

    assert not (tmp_path / "recipients.toml").exists()


def test_an_empty_unsubscribed_list_is_accepted(tmp_path):
    """Contrairement aux destinataires : n'avoir aucun désabonné est plausible."""
    empty_unsub = {**COMPLETE,
                   "config/unsubscribed.toml": '[unsubscribed]\nemails = []\ntimestamps = []\n'}

    report = fetch_subscriber_data(tmp_path, fetch=_fetcher(empty_unsub))

    assert report["config/unsubscribed.toml"] == 0
