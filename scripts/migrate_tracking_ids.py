"""
Migration des mesures vers des identifiants opaques.

Remplace, dans tous les fichiers `data/*.csv`, le SHA-256 non salé de l'adresse
email par un identifiant tiré au sort. L'historique d'engagement est préservé —
les chiffres restent exploitables — mais plus rien ne permet de remonter d'une
ligne de mesure à une personne sans la table de correspondance.

Les hashs absents de `recipients.toml` (abonnés partis depuis) reçoivent un
marqueur `orphan-N` stable : leurs lignes sont conservées pour ne pas fausser
les volumes, sans possibilité de ré-identification.

Usage :
    venv/bin/python scripts/migrate_tracking_ids.py --dry-run   # simulation
    venv/bin/python scripts/migrate_tracking_ids.py             # écriture
"""

import argparse
import csv
import hashlib
import logging
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.subscriber_ids import SubscriberIds  # noqa: E402

logger = logging.getLogger(__name__)

HASH_COLUMN = "email_hash"
ORPHAN_PREFIX = "orphan-"


def sha256_of(email: str) -> str:
    """L'ancien identifiant : SHA-256 non salé, tel que produit jusqu'ici."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()


def load_recipients(path: Path) -> list[str]:
    with open(path, "rb") as fh:
        return tomllib.load(fh).get("recipients", {}).get("emails", [])


def migrate_directory(
    data_dir: Path,
    ids: SubscriberIds,
    subscribers: list[str],
    dry_run: bool = False,
) -> dict:
    """
    Réécrit chaque CSV du dossier en substituant les anciens hashs.

    Retourne un rapport {files, rows, mapped, orphaned}. `dry_run` compte
    sans rien écrire.
    """
    # Table arc-en-ciel : ancien hash → identifiant opaque.
    # En simulation, on tire des identifiants jetables plutôt que de créer la
    # table : « --dry-run » ne doit produire aucun fichier, y compris celui-là.
    if dry_run:
        from tools.subscriber_ids import new_identifier

        rainbow = {
            sha256_of(email): (ids.get(email) or new_identifier())
            for email in subscribers
        }
    else:
        rainbow = {sha256_of(email): ids.get_or_create(email) for email in subscribers}
    known_ids = set(rainbow.values())

    orphans: dict[str, str] = {}
    report = {"files": 0, "rows": 0, "mapped": 0, "orphaned": 0}

    def translate(value: str) -> str:
        if value in rainbow:
            report["mapped"] += 1
            return rainbow[value]
        # Déjà migré : on ne retouche pas (idempotence)
        if value in known_ids or value.startswith(ORPHAN_PREFIX):
            report["mapped"] += 1
            return value
        # Hash inconnu — abonné parti. Marqueur stable pour ne pas
        # transformer un même lecteur en plusieurs orphelins distincts.
        if value not in orphans:
            orphans[value] = f"{ORPHAN_PREFIX}{len(orphans) + 1}"
        report["orphaned"] += 1
        return orphans[value]

    for path in sorted(data_dir.glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            if HASH_COLUMN not in fieldnames:
                continue
            rows = list(reader)

        report["files"] += 1
        report["rows"] += len(rows)
        for row in rows:
            row[HASH_COLUMN] = translate(row.get(HASH_COLUMN, ""))

        if dry_run:
            continue

        # Réécriture atomique : un fichier temporaire remplacé d'un bloc, pour
        # qu'une interruption ne laisse jamais un CSV à moitié écrit.
        tmp = path.with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(path)

    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Compte ce qui serait fait, sans rien écrire")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    subscribers = load_recipients(ROOT / "config" / "recipients.toml")
    ids = SubscriberIds()

    logger.info(f"{len(subscribers)} abonnés · dossier {data_dir}")
    if args.dry_run:
        logger.info("SIMULATION — aucun fichier ne sera modifié\n")

    report = migrate_directory(data_dir, ids, subscribers, dry_run=args.dry_run)

    logger.info(
        f"\n{report['files']} fichiers · {report['rows']} lignes\n"
        f"  {report['mapped']} rattachées à un abonné connu\n"
        f"  {report['orphaned']} orphelines (abonnés partis)"
    )
    if not args.dry_run:
        logger.info(f"\nTable de correspondance : {ids.path}")
        logger.info("⚠️  Ce fichier est le seul lien entre les mesures et les personnes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
