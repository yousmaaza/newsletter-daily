"""
Tests de la purge de rétention.

Applique ce que la page vie privée annonce aux lecteurs :
  - mesures (ouvertures, clics, réactions) : 12 mois, puis agrégées sans identifiant
  - avis rattachés à un identifiant : effacés en même temps que lui
  - motifs de départ : conservés, le fichier ne portant aucun identifiant

Les volumes sont toujours préservés : purger ne doit pas faire mentir les
chiffres publiés sur /board.
"""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.apply_retention import ARCHIVED, apply_retention

TODAY = date(2026, 8, 26)
RECENT = (TODAY - timedelta(days=30)).isoformat()
OLD = (TODAY - timedelta(days=400)).isoformat()       # > 12 mois
MIDDLE = (TODAY - timedelta(days=120)).isoformat()    # > 3 mois, < 12 mois


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture
def data_dir(tmp_path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    for day, ident in ((RECENT, "id-recent"), (OLD, "id-ancien")):
        (d / f"opens_{day}.csv").write_text(
            '"timestamp","email_hash","send_date"\n'
            f'"{day}T06:00:00Z","{ident}","{day}"\n', encoding="utf-8")

    (d / f"feedback_{OLD}.csv").write_text(
        '"timestamp","email_hash","send_date","global_reaction","comment"\n'
        f'"{OLD}T06:00:00Z","id-ancien","{OLD}","like","Un avis très reconnaissable"\n',
        encoding="utf-8")

    (d / "unsubscribe_reasons.csv").write_text(
        '"timestamp","send_date","reasons","free_text"\n'
        f'"{RECENT}T10:00:00","{RECENT}","too_long","Commentaire récent"\n'
        f'"{MIDDLE}T10:00:00","{MIDDLE}","other","Commentaire ancien"\n',
        encoding="utf-8")
    return d


# ── Mesures : 12 mois ────────────────────────────────────────────────────────

def test_recent_measures_keep_their_identifier(data_dir):
    apply_retention(data_dir, today=TODAY)

    assert _rows(data_dir / f"opens_{RECENT}.csv")[0]["email_hash"] == "id-recent"


def test_measures_beyond_twelve_months_lose_their_identifier(data_dir):
    apply_retention(data_dir, today=TODAY)

    assert _rows(data_dir / f"opens_{OLD}.csv")[0]["email_hash"] == ARCHIVED


def test_archived_rows_are_kept_so_volumes_stay_true(data_dir):
    """Les totaux publiés sur /board ne doivent pas bouger après purge."""
    apply_retention(data_dir, today=TODAY)

    assert len(_rows(data_dir / f"opens_{OLD}.csv")) == 1


def test_an_old_comment_is_erased(data_dir):
    apply_retention(data_dir, today=TODAY)
    row = _rows(data_dir / f"feedback_{OLD}.csv")[0]

    assert row["comment"] == ""
    assert row["global_reaction"] == "like"      # la réaction, elle, reste


# ── Motifs de départ : conservés ─────────────────────────────────────────────
#
# Contrairement aux avis en bas d'édition, ce fichier ne porte AUCUN
# identifiant depuis 185b90e : la colonne email en a été retirée. Le texte
# n'est donc rattaché à personne, et rien ne justifie de le détruire — c'est
# du retour produit exploitable.

def test_a_recent_departure_comment_is_kept(data_dir):
    apply_retention(data_dir, today=TODAY)

    assert _rows(data_dir / "unsubscribe_reasons.csv")[0]["free_text"] == "Commentaire récent"


def test_an_old_departure_comment_is_also_kept(data_dir):
    """Sans identifiant dans le fichier, l'ancienneté ne change rien."""
    apply_retention(data_dir, today=TODAY)

    assert _rows(data_dir / "unsubscribe_reasons.csv")[1]["free_text"] == "Commentaire ancien"


def test_the_departure_reasons_are_untouched(data_dir):
    apply_retention(data_dir, today=TODAY)
    rows = _rows(data_dir / "unsubscribe_reasons.csv")

    assert [r["reasons"] for r in rows] == ["too_long", "other"]


def test_the_reasons_file_is_never_rewritten(data_dir):
    before = (data_dir / "unsubscribe_reasons.csv").read_text(encoding="utf-8")

    apply_retention(data_dir, today=TODAY)

    assert (data_dir / "unsubscribe_reasons.csv").read_text(encoding="utf-8") == before


# ── Sûreté ───────────────────────────────────────────────────────────────────

def test_a_dry_run_writes_nothing(data_dir):
    before = (data_dir / f"opens_{OLD}.csv").read_text(encoding="utf-8")

    report = apply_retention(data_dir, today=TODAY, dry_run=True)

    assert (data_dir / f"opens_{OLD}.csv").read_text(encoding="utf-8") == before
    assert report["measures_archived"] == 2   # opens ancien + feedback ancien


def test_running_twice_changes_nothing_more(data_dir):
    apply_retention(data_dir, today=TODAY)
    after = (data_dir / f"opens_{OLD}.csv").read_text(encoding="utf-8")

    apply_retention(data_dir, today=TODAY)

    assert (data_dir / f"opens_{OLD}.csv").read_text(encoding="utf-8") == after


def test_nothing_old_enough_means_nothing_happens(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / f"opens_{RECENT}.csv").write_text(
        f'"timestamp","email_hash","send_date"\n"{RECENT}T06:00:00Z","id-x","{RECENT}"\n',
        encoding="utf-8")

    report = apply_retention(d, today=TODAY)

    assert report["measures_archived"] == 0
    assert _rows(d / f"opens_{RECENT}.csv")[0]["email_hash"] == "id-x"


def test_the_report_counts_both_kinds(data_dir):
    report = apply_retention(data_dir, today=TODAY)

    assert report["measures_archived"] == 2      # opens ancien + feedback ancien
    assert report["comments_erased"] == 1        # le seul avis rattaché à un identifiant
