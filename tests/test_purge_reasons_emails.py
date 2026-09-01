"""
Tests du retrait des adresses du fichier des motifs de désinscription.

Le fichier historique contient une colonne `email` en clair, qui ne sert à
rien : `build_dashboard_data.py` ne lit que timestamp, reasons et free_text.
"""

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.purge_reasons_emails import purge_reasons_file

LEGACY = (
    "timestamp,email,send_date,reasons,free_text\n"
    '"2026-04-01T10:00:00","parti@example.com","2026-03-31","too_long",""\n'
    '"2026-05-09T11:00:00","autre@example.com","2026-05-09","other","Pas assez de finance"\n'
)


@pytest.fixture
def legacy_file(tmp_path) -> Path:
    path = tmp_path / "unsubscribe_reasons.csv"
    path.write_text(LEGACY, encoding="utf-8")
    return path


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_no_address_survives(legacy_file):
    purge_reasons_file(legacy_file)

    assert "@example.com" not in legacy_file.read_text(encoding="utf-8")


def test_the_email_column_is_gone(legacy_file):
    purge_reasons_file(legacy_file)

    assert "email" not in _rows(legacy_file)[0]


def test_no_row_is_lost(legacy_file):
    purge_reasons_file(legacy_file)

    assert len(_rows(legacy_file)) == 2


def test_the_reasons_are_kept(legacy_file):
    rows = purge_reasons_file(legacy_file) and _rows(legacy_file)

    assert [r["reasons"] for r in rows] == ["too_long", "other"]


def test_the_free_text_is_kept(legacy_file):
    """Le commentaire reste, mais détaché de toute personne."""
    rows = purge_reasons_file(legacy_file) and _rows(legacy_file)

    assert rows[1]["free_text"] == "Pas assez de finance"


def test_the_timestamps_are_kept(legacy_file):
    rows = purge_reasons_file(legacy_file) and _rows(legacy_file)

    assert rows[0]["timestamp"] == "2026-04-01T10:00:00"
    assert rows[0]["send_date"] == "2026-03-31"


def test_running_twice_changes_nothing_more(legacy_file):
    purge_reasons_file(legacy_file)
    after = legacy_file.read_text(encoding="utf-8")

    purge_reasons_file(legacy_file)

    assert legacy_file.read_text(encoding="utf-8") == after


def test_an_already_clean_file_is_left_alone(tmp_path):
    clean = tmp_path / "reasons.csv"
    clean.write_text(
        'timestamp,send_date,reasons,free_text\n"2026-08-01T09:00:00","2026-08-01","other",""\n',
        encoding="utf-8")
    before = clean.read_text(encoding="utf-8")

    purge_reasons_file(clean)

    assert clean.read_text(encoding="utf-8") == before


def test_a_missing_file_is_not_an_error(tmp_path):
    assert purge_reasons_file(tmp_path / "absent.csv") == 0


def test_the_report_counts_the_rows_cleaned(legacy_file):
    assert purge_reasons_file(legacy_file) == 2
