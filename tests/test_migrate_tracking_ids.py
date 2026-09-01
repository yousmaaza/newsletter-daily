"""
Tests de la migration des mesures vers les identifiants opaques.

La migration réécrit 101 fichiers de données historiques. Une erreur y est
irréversible, d'où des tests sur chaque garantie :
  - aucune ligne perdue
  - aucun ancien hash survivant
  - les colonnes non concernées intactes
  - un hash inconnu rendu orphelin plutôt que laissé en clair
"""

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.migrate_tracking_ids import migrate_directory, sha256_of

SUBSCRIBERS = ["alice@example.com", "bob@example.com"]


@pytest.fixture
def data_dir(tmp_path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    a, b = (sha256_of(e) for e in SUBSCRIBERS)
    unknown = "f" * 64   # abonné parti, absent de recipients.toml

    (d / "opens_2026-08-25.csv").write_text(
        '"timestamp","email_hash","send_date"\n'
        f'"2026-08-25T06:00:00Z","{a}","2026-08-25"\n'
        f'"2026-08-25T07:00:00Z","{b}","2026-08-25"\n'
        f'"2026-08-25T08:00:00Z","{unknown}","2026-08-25"\n',
        encoding="utf-8")

    (d / "clicks_2026-08-25.csv").write_text(
        '"timestamp","email_hash","article_rank","target_url","send_date"\n'
        f'"2026-08-25T09:00:00Z","{a}","3","https://lefigaro.fr/x","2026-08-25"\n',
        encoding="utf-8")
    return d


@pytest.fixture
def ids(tmp_path):
    from tools.subscriber_ids import SubscriberIds

    store = SubscriberIds(tmp_path / "ids.toml")
    for email in SUBSCRIBERS:
        store.get_or_create(email)
    return store


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ── Garanties ────────────────────────────────────────────────────────────────

def test_no_row_is_lost(data_dir, ids):
    migrate_directory(data_dir, ids, SUBSCRIBERS)

    assert len(_rows(data_dir / "opens_2026-08-25.csv")) == 3
    assert len(_rows(data_dir / "clicks_2026-08-25.csv")) == 1


def test_known_hashes_become_their_opaque_identifier(data_dir, ids):
    migrate_directory(data_dir, ids, SUBSCRIBERS)
    values = {r["email_hash"] for r in _rows(data_dir / "opens_2026-08-25.csv")}

    assert ids.get("alice@example.com") in values
    assert ids.get("bob@example.com") in values


def test_no_reversible_hash_survives_anywhere(data_dir, ids):
    migrate_directory(data_dir, ids, SUBSCRIBERS)
    body = "".join(p.read_text(encoding="utf-8") for p in data_dir.glob("*.csv"))

    for email in SUBSCRIBERS:
        assert sha256_of(email) not in body


def test_an_unknown_hash_becomes_an_orphan_marker(data_dir, ids):
    """Un abonné parti n'est pas dans la table : sa ligne est conservée, anonyme."""
    migrate_directory(data_dir, ids, SUBSCRIBERS)
    values = [r["email_hash"] for r in _rows(data_dir / "opens_2026-08-25.csv")]

    assert any(v.startswith("orphan-") for v in values)
    assert "f" * 64 not in values


def test_the_same_unknown_hash_maps_to_the_same_orphan(tmp_path, ids):
    """Sinon les statistiques de fidélité seraient faussées."""
    d = tmp_path / "data"
    d.mkdir()
    unknown = "e" * 64
    for day in ("2026-08-24", "2026-08-25"):
        (d / f"opens_{day}.csv").write_text(
            f'"timestamp","email_hash","send_date"\n"{day}T06:00:00Z","{unknown}","{day}"\n',
            encoding="utf-8")

    migrate_directory(d, ids, SUBSCRIBERS)
    values = {r["email_hash"] for p in d.glob("*.csv") for r in _rows(p)}

    assert len(values) == 1


def test_other_columns_are_untouched(data_dir, ids):
    migrate_directory(data_dir, ids, SUBSCRIBERS)
    row = _rows(data_dir / "clicks_2026-08-25.csv")[0]

    assert row["article_rank"] == "3"
    assert row["target_url"] == "https://lefigaro.fr/x"
    assert row["send_date"] == "2026-08-25"
    assert row["timestamp"] == "2026-08-25T09:00:00Z"


def test_the_header_is_preserved(data_dir, ids):
    migrate_directory(data_dir, ids, SUBSCRIBERS)
    header = (data_dir / "opens_2026-08-25.csv").read_text(encoding="utf-8").splitlines()[0]

    assert "email_hash" in header
    assert "send_date" in header


def test_the_report_counts_what_was_done(data_dir, ids):
    report = migrate_directory(data_dir, ids, SUBSCRIBERS)

    assert report["files"] == 2
    assert report["rows"] == 4
    assert report["mapped"] == 3
    assert report["orphaned"] == 1


# ── Idempotence et sûreté ────────────────────────────────────────────────────

def test_running_twice_changes_nothing_more(data_dir, ids):
    migrate_directory(data_dir, ids, SUBSCRIBERS)
    after_first = (data_dir / "opens_2026-08-25.csv").read_text(encoding="utf-8")

    migrate_directory(data_dir, ids, SUBSCRIBERS)

    assert (data_dir / "opens_2026-08-25.csv").read_text(encoding="utf-8") == after_first


def test_a_dry_run_writes_nothing(data_dir, ids):
    before = (data_dir / "opens_2026-08-25.csv").read_text(encoding="utf-8")

    report = migrate_directory(data_dir, ids, SUBSCRIBERS, dry_run=True)

    assert (data_dir / "opens_2026-08-25.csv").read_text(encoding="utf-8") == before
    assert report["rows"] == 4


def test_a_file_without_the_column_is_left_alone(tmp_path, ids):
    d = tmp_path / "data"
    d.mkdir()
    other = d / "autre.csv"
    other.write_text("a,b\n1,2\n", encoding="utf-8")

    migrate_directory(d, ids, SUBSCRIBERS)

    assert other.read_text(encoding="utf-8") == "a,b\n1,2\n"


def test_a_dry_run_does_not_create_the_identifier_table(tmp_path, data_dir):
    """Une simulation ne doit rien écrire — pas même la table de correspondance."""
    from tools.subscriber_ids import SubscriberIds

    table = tmp_path / "ids-absent.toml"
    migrate_directory(data_dir, SubscriberIds(table), SUBSCRIBERS, dry_run=True)

    assert not table.exists()
