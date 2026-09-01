"""
Retrait des adresses email du fichier des motifs de désinscription.

`data/unsubscribe_reasons.csv` stockait l'adresse en clair — le seul fichier
de données à le faire. Elle n'a jamais servi : `build_dashboard_data.py` n'en
lit que `timestamp`, `reasons` et `free_text`.

Ce sont les personnes ayant explicitement quitté la newsletter : elles ont
moins de raisons que quiconque de figurer encore nominativement dans les
fichiers. La colonne est supprimée ; motifs et commentaires sont conservés,
détachés de toute personne.

Usage :
    venv/bin/python scripts/purge_reasons_emails.py [--dry-run]
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REASONS_PATH = ROOT / "data" / "unsubscribe_reasons.csv"

logger = logging.getLogger(__name__)

DROPPED_COLUMNS = ("email", "email_hash")


def purge_reasons_file(path: Path, dry_run: bool = False) -> int:
    """
    Supprime les colonnes identifiantes du fichier.

    Retourne le nombre de lignes nettoyées. Idempotent : sur un fichier déjà
    propre, ne réécrit rien.
    """
    path = Path(path)
    if not path.exists():
        logger.info(f"{path} absent — rien à faire")
        return 0

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    to_drop = [c for c in DROPPED_COLUMNS if c in fieldnames]
    if not to_drop:
        logger.info(f"{path.name} ne contient aucune colonne identifiante — inchangé")
        return 0

    kept = [c for c in fieldnames if c not in to_drop]
    cleaned = [{c: row.get(c, "") for c in kept} for row in rows]

    if dry_run:
        logger.info(f"SIMULATION — {len(cleaned)} lignes, colonnes retirées : {', '.join(to_drop)}")
        return len(cleaned)

    # Réécriture atomique : une interruption ne doit pas laisser un fichier
    # à moitié écrit, avec des adresses dans la partie non réécrite.
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=kept, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(cleaned)
    tmp.replace(path)

    logger.info(f"{path.name} — {len(cleaned)} lignes, colonnes retirées : {', '.join(to_drop)}")
    return len(cleaned)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", default=str(REASONS_PATH))
    args = parser.parse_args()

    count = purge_reasons_file(Path(args.path), dry_run=args.dry_run)
    if count and not args.dry_run:
        logger.info(
            "\n⚠️  Les adresses restent dans l'historique git, y compris dans les\n"
            "   messages de commit « data: unsubscribe reason from <adresse> ».\n"
            "   Seul un git filter-repo les effacera — à faire avant d'ouvrir le dépôt."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
