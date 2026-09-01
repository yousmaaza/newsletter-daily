"""
Tests de la prévisualisation locale.

Propriété critique : une prévisualisation ne doit contacter personne et ne
doit produire aucune URL de mesure — c'est ce qui la rend sûre à lancer
autant de fois qu'on veut pendant qu'on itère sur le format.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.newsletter_renderer import write_preview

NEWSLETTER = {
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


@pytest.fixture
def saved_newsletter(tmp_path) -> Path:
    """Reproduit l'arborescence output/newsletter/{date}/data.json."""
    day = tmp_path / "newsletter" / "2026-08-25"
    day.mkdir(parents=True)
    (day / "data.json").write_text(json.dumps(NEWSLETTER, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "newsletter"


def test_preview_writes_a_readable_html_file(saved_newsletter, tmp_path):
    out = write_preview("2026-08-25", data_root=saved_newsletter, out_dir=tmp_path / "preview")

    assert out.exists()
    assert "Tornade dans l'Aude" in out.read_text(encoding="utf-8")


def test_preview_contains_no_tracking_url(saved_newsletter, tmp_path):
    out = write_preview("2026-08-25", data_root=saved_newsletter, out_dir=tmp_path / "preview")
    html = out.read_text(encoding="utf-8")

    assert "/pixel" not in html
    assert "/click?" not in html


def test_preview_on_a_missing_date_says_which_file_is_missing(saved_newsletter, tmp_path):
    with pytest.raises(FileNotFoundError, match="2026-01-01"):
        write_preview("2026-01-01", data_root=saved_newsletter, out_dir=tmp_path / "preview")


def test_preview_can_show_the_transparency_block(saved_newsletter, tmp_path):
    out = write_preview(
        "2026-08-25", data_root=saved_newsletter, out_dir=tmp_path / "preview", with_notice=True
    )
    html = out.read_text(encoding="utf-8")

    assert "Ce que je mesure" in html


def test_preview_with_the_block_still_has_no_tracking_pixel(saved_newsletter, tmp_path):
    """Le bloc parle de mesure — il ne doit pas en déclencher une au passage."""
    out = write_preview(
        "2026-08-25", data_root=saved_newsletter, out_dir=tmp_path / "preview", with_notice=True
    )

    assert "/pixel" not in out.read_text(encoding="utf-8")


def test_preview_without_the_flag_shows_no_block(saved_newsletter, tmp_path):
    out = write_preview("2026-08-25", data_root=saved_newsletter, out_dir=tmp_path / "preview")

    assert "Ce que je mesure" not in out.read_text(encoding="utf-8")


def test_preview_refuses_incomplete_data(tmp_path):
    """Le data.json versionné sur GitHub ne contient que rank+title."""
    day = tmp_path / "newsletter" / "2026-08-25"
    day.mkdir(parents=True)
    (day / "data.json").write_text(
        json.dumps({"articles": [{"rank": 1, "title": "Titre seul"}]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="incomplètes"):
        write_preview("2026-08-25", data_root=tmp_path / "newsletter", out_dir=tmp_path / "preview")
