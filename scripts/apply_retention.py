"""
Purge de rétention des données de mesure.

Applique les durées annoncées aux lecteurs sur la page vie privée :

  ┌────────────────────────────────────┬──────────────────────────────────────┐
  │ Ouvertures, clics, réactions, avis │ 12 mois, puis désidentifiés          │
  │ Texte libre d'un avis              │ effacé avec l'identifiant qui le porte│
  │ Motifs de départ                   │ conservés — aucun identifiant dedans │
  └────────────────────────────────────┴──────────────────────────────────────┘

Principe : on n'efface jamais une ligne, on la **désidentifie**. Les volumes
publiés sur /board — nombre d'ouvertures, de clics, d'éditions — restent donc
exacts après purge. Ce qui disparaît, c'est le lien avec une personne et le
texte qu'elle a écrit.

À lancer périodiquement. Sans planification, une politique de rétention n'est
qu'une promesse.

Usage :
    venv/bin/python scripts/apply_retention.py [--dry-run]
"""

import argparse
import csv
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

MEASURE_RETENTION_DAYS = 365   # ouvertures, clics, réactions, avis

ARCHIVED = "archived"          # remplace l'identifiant au-delà de 12 mois
HASH_COLUMN = "email_hash"
COMMENT_COLUMNS = ("comment", "free_text")

DATED_FILE = re.compile(r"_(\d{4}-\d{2}-\d{2})\.csv$")


def _file_date(path: Path) -> date | None:
    """Date portée par le nom du fichier, ex. opens_2026-08-25.csv."""
    match = DATED_FILE.search(path.name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _row_date(row: dict) -> date | None:
    """Date d'une ligne, depuis send_date puis timestamp."""
    for key in ("send_date", "timestamp"):
        value = (row.get(key) or "")[:10]
        try:
            return date.fromisoformat(value)
        except ValueError:
            continue
    return None


def _rewrite(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Réécriture atomique — une interruption ne laisse jamais un fichier partiel."""
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def apply_retention(
    data_dir: Path,
    today: date | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Désidentifie les données au-delà de leur durée de conservation.

    Retourne {measures_archived, comments_erased, files_touched}.
    Idempotent : une ligne déjà archivée n'est pas recomptée.
    """
    today = today or date.today()
    measure_cutoff = today - timedelta(days=MEASURE_RETENTION_DAYS)

    report = {"measures_archived": 0, "comments_erased": 0, "files_touched": 0}

    for path in sorted(Path(data_dir).glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
        if not fieldnames:
            continue

        file_date = _file_date(path)
        changed = False

        for row in rows:
            when = file_date or _row_date(row)
            if when is None:
                continue

            # Au-delà de 12 mois : l'identifiant disparaît, la ligne reste
            if (
                HASH_COLUMN in fieldnames
                and when < measure_cutoff
                and row.get(HASH_COLUMN) != ARCHIVED
            ):
                row[HASH_COLUMN] = ARCHIVED
                report["measures_archived"] += 1
                changed = True

            # Texte libre : effacé uniquement là où il est rattaché à un
            # identifiant, donc en même temps que celui-ci. Le fichier des
            # motifs de départ n'en porte aucun (colonne email retirée) : son
            # texte n'est lié à personne et reste un retour produit exploitable.
            if HASH_COLUMN not in fieldnames:
                continue
            for column in COMMENT_COLUMNS:
                if column in fieldnames and when < measure_cutoff and row.get(column):
                    row[column] = ""
                    report["comments_erased"] += 1
                    changed = True

        if changed:
            report["files_touched"] += 1
            if not dry_run:
                _rewrite(path, fieldnames, rows)

    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    args = parser.parse_args()

    if args.dry_run:
        logger.info("SIMULATION — aucun fichier ne sera modifié\n")

    report = apply_retention(Path(args.data_dir), dry_run=args.dry_run)

    logger.info(
        f"{report['files_touched']} fichiers concernés\n"
        f"  {report['measures_archived']} mesures désidentifiées (> {MEASURE_RETENTION_DAYS} j)\n"
        f"  {report['comments_erased']} textes libres effacés"
    )
    if not report["files_touched"]:
        logger.info("\nRien n'a encore atteint sa durée de conservation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
