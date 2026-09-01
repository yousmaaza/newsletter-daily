"""
Chiffres d'engagement affichés dans le bloc transparence de la newsletter.

Ces valeurs partent chez les lecteurs : elles sont calculées depuis les CSV de
`data/` (mêmes sources que le tableau de bord) et n'exposent aucun identifiant —
uniquement des compteurs agrégés.
"""

import csv
import glob
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"

BAR_MAX_PX = 68   # hauteur de la barre du mois le plus fort, en pixels
BAR_MIN_PX = 3    # plancher : une barre à zéro reste visible
TREND_MONTHS = 4  # nombre de mois affichés dans le graphe

# Le mois courant et les mois faibles sont tramés en clair pour ne pas laisser
# croire à une progression continue : la période creuse reste lisible.
BAR_STRONG = "#c9001e"
BAR_PALE = "#f0b8bf"


def _read_rows(directory: Path, pattern: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(glob.glob(str(directory / pattern))):
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                rows.extend(csv.DictReader(handle))
        except (OSError, csv.Error) as exc:
            logger.warning(f"Fichier de mesures illisible ignoré ({path}) : {exc}")
    return rows


def _month_of(filename: str, prefix: str) -> str:
    """opens_2026-08-25.csv → '2026-08'"""
    return Path(filename).stem[len(prefix):][:7]


def compute_transparency_stats(
    data_dir: Optional[Path] = None,
    subscriber_count: int = 0,
) -> dict:
    """
    Agrège les chiffres du bloc transparence.

    Retourne total_editions, unique_readers, open_rate_pct et click_trend
    (une entrée par mois, avec la hauteur de barre déjà calculée).
    """
    directory = data_dir or DATA_DIR

    open_files = sorted(glob.glob(str(directory / "opens_*.csv")))
    total_editions = len(open_files)

    # Ouvreurs distincts par édition, et sur toute la période
    openers_per_edition: list[int] = []
    all_readers: set[str] = set()
    editions_per_month: defaultdict[str, int] = defaultdict(int)

    for path in open_files:
        rows = _read_rows(directory, Path(path).name)
        hashes = {r.get("email_hash", "") for r in rows if r.get("email_hash")}
        openers_per_edition.append(len(hashes))
        all_readers |= hashes
        editions_per_month[_month_of(path, "opens_")] += 1

    # Le dénominateur ne peut pas être plus petit que le nombre d'ouvreurs
    # observés sur une seule édition : on ne peut pas avoir plus de lecteurs
    # que d'abonnés. Cette contrainte rend le calcul auto-correcteur quand la
    # liste transmise est tronquée — ci-validate.yml écrase recipients.toml
    # avec une seule adresse, ce qui avait produit un « 1686 % » dans le bloc.
    open_rate_pct = 0
    if openers_per_edition:
        average_openers = sum(openers_per_edition) / len(openers_per_edition)
        denominator = max(subscriber_count, max(openers_per_edition))
        if denominator > 0:
            open_rate_pct = min(100, round(average_openers / denominator * 100))

    # Clics par mois
    clicks_per_month: defaultdict[str, int] = defaultdict(int)
    for path in sorted(glob.glob(str(directory / "clicks_*.csv"))):
        rows = _read_rows(directory, Path(path).name)
        clicks_per_month[_month_of(path, "clicks_")] += len(rows)

    months = sorted(editions_per_month)[-TREND_MONTHS:]
    values = {
        month: round(clicks_per_month.get(month, 0) / editions_per_month[month], 1)
        for month in months
    }
    peak = max(values.values(), default=0)

    click_trend = [
        {
            "month": month,
            "label": _month_label(month),
            "value": values[month],          # valeur numérique, pour la logique
            "display": _fr_number(values[month]),  # '1,5' — pour l'affichage
            "height": (
                max(BAR_MIN_PX, round(values[month] / peak * BAR_MAX_PX)) if peak else BAR_MIN_PX
            ),
            "color": BAR_STRONG if peak and values[month] >= peak / 2 else BAR_PALE,
        }
        for month in months
    ]

    return {
        "total_editions": total_editions,
        "unique_readers": len(all_readers),
        "open_rate_pct": open_rate_pct,
        "click_trend": click_trend,
    }


_MONTH_LABELS = [
    "Janv.", "Févr.", "Mars", "Avril", "Mai", "Juin",
    "Juil.", "Août", "Sept.", "Oct.", "Nov.", "Déc.",
]


def _month_label(month: str) -> str:
    """'2026-08' → 'Août'"""
    try:
        return _MONTH_LABELS[int(month.split("-")[1]) - 1]
    except (ValueError, IndexError):
        return month


def _fr_number(value: float) -> str:
    """1.5 → '1,5' — séparateur décimal français."""
    return f"{value:.1f}".replace(".", ",")
