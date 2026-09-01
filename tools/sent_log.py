"""
Journal des éditions réellement envoyées.

Le planificateur de GitHub Actions fonctionne « au mieux » : le 27 et le
28 août 2026, le déclenchement de 5 h UTC s'est réveillé onze puis douze heures
plus tard. Entre-temps l'envoi avait été relancé à la main — et le run tardif a
renvoyé la même édition à tout le monde.

Ce module ne répare pas le planificateur, on ne peut pas. Il rend la relance
inoffensive : une édition déjà partie ne repart pas.

Le fichier ne contient que des dates et des comptages. Il est suivi par git et
deviendra public avec le dépôt — aucune adresse ne doit y entrer.
"""

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "sent_editions.csv"
HEADER = ["date", "recipients"]


def _path(path: Path | None) -> Path:
    return Path(path) if path is not None else DEFAULT_PATH


def already_sent(date_str: str, path: Path | None = None) -> bool:
    """
    Dit si l'édition de `date_str` est déjà partie.

    En cas de fichier illisible on renvoie False, donc l'envoi a lieu. C'est un
    choix : un doublon se constate et s'excuse, une édition muette passe
    inaperçue et ne se rattrape pas.
    """
    target = _path(path)
    if not target.exists():
        return False
    try:
        with open(target, newline="", encoding="utf-8") as f:
            return any(row and row[0].strip() == date_str for row in csv.reader(f))
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        logger.error(
            f"Journal d'envoi illisible ({target}) : {e}. "
            "L'envoi est autorisé — vérifier le fichier, un doublon est possible."
        )
        return False


def record_send(date_str: str, recipients: int, path: Path | None = None) -> None:
    """Inscrit une édition partie. Réécrire la même date ne duplique pas la ligne."""
    target = _path(path)
    if already_sent(date_str, path=target):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    nouveau = not target.exists() or target.stat().st_size == 0
    with open(target, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nouveau:
            w.writerow(HEADER)
        w.writerow([date_str, recipients])
    logger.info(f"Édition {date_str} inscrite au journal d'envoi ({recipients} destinataires)")
