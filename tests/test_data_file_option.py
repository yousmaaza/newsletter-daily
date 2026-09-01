"""
Tests de la source de données explicite pour l'envoi de test.

Permet de valider le rendu sans lancer la génération : la CI peut ainsi
vérifier un template ou le bloc transparence sans consommer de crédits
Anthropic, ce qui est le cas de la grande majorité des validations.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.newsletter_renderer import load_newsletter_data

SAMPLE = {
    "subject": "Sujet",
    "newsletter_title": "Titre",
    "intro": "Intro.",
    "conclusion": "Fin.",
    "articles": [
        {
            "rank": 1, "title": "Un titre", "flash": "Flash.", "detail": "Détail.",
            "topic": "monde", "hype": "viral",
            "sources": [{"title": "S", "url": "https://x.fr", "source": "x.fr"}],
        }
    ],
}


@pytest.fixture
def sample_file(tmp_path) -> Path:
    p = tmp_path / "edition.json"
    p.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    return p


def test_an_explicit_path_is_loaded(sample_file):
    assert load_newsletter_data("2026-08-25", data_file=sample_file)["newsletter_title"] == "Titre"


def test_the_explicit_path_wins_over_the_date(tmp_path, sample_file):
    """La date reste utilisée pour l'affichage, pas pour trouver le fichier."""
    data = load_newsletter_data("2099-01-01", data_file=sample_file, data_root=tmp_path)

    assert data["articles"][0]["title"] == "Un titre"


def test_a_missing_explicit_path_names_the_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="absent.json"):
        load_newsletter_data("2026-08-25", data_file=tmp_path / "absent.json")


def test_an_incomplete_explicit_file_is_refused(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"articles": [{"rank": 1, "title": "T"}]}), encoding="utf-8")

    with pytest.raises(ValueError, match="incomplètes"):
        load_newsletter_data("2026-08-25", data_file=bad)


def test_without_the_option_the_date_is_used(tmp_path):
    day = tmp_path / "2026-08-25"
    day.mkdir()
    (day / "data.json").write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")

    assert load_newsletter_data("2026-08-25", data_root=tmp_path)["newsletter_title"] == "Titre"


# ── L'édition de référence versionnée ────────────────────────────────────────

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "newsletter_sample.json"


def test_the_reference_edition_exists():
    assert FIXTURE.exists(), "l'édition de référence utilisée par la CI est absente"


def test_the_reference_edition_is_complete():
    """Elle doit passer la validation, sinon la CI échouera sur son propre jeu."""
    data = load_newsletter_data("2026-08-25", data_file=FIXTURE)

    assert len(data["articles"]) >= 5


def test_the_reference_edition_carries_no_personal_data():
    """Elle est versionnée : elle ne doit contenir que de l'information publique."""
    import re

    body = FIXTURE.read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", body, re.I)
    assert not re.search(r"\b[0-9a-f]{64}\b", body)
