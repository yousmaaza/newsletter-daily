"""
Récupération des données d'abonnés depuis le dépôt privé dédié (#55).

Les listes d'abonnés, de désinscrits et la table d'identifiants ne vivent plus
dans ce dépôt : elles sont dans `DATA_REPO`, privé, pour que le dépôt applicatif
puisse être ouvert sans publier cinq mois d'historique de lecture nominatif.

Ce script les rapatrie dans `config/` avant que le pipeline ne démarre. Ce choix
— une étape explicite plutôt qu'une lecture distante au moment de l'envoi —
tient à une chose : **l'échec doit être bruyant et précoce**. Un appel réseau
enfoui dans le chemin d'envoi échouerait au pire moment, et la tentation serait
grande de le laisser retomber sur une liste vide.

Règle : tout ou rien. Rien n'est écrit tant que les trois fichiers ne sont pas
récupérés et validés. Un `config/` à moitié écrit serait pire qu'un échec net —
l'envoi partirait à une liste tronquée sans que rien ne le signale.

Usage :
    venv/bin/python scripts/fetch_subscriber_data.py
"""

import argparse
import base64
import logging
import os
import sys
import tomllib
from pathlib import Path
from typing import Callable, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

logger = logging.getLogger(__name__)

# Fichier → (section TOML, l'absence d'entrées est-elle plausible ?)
SUBSCRIBER_FILES: dict[str, tuple[str, bool]] = {
    # Une liste de destinataires vide est plus probablement un échec de lecture
    # qu'un état réel : on refuse plutôt que d'envoyer à personne.
    "config/recipients.toml":     ("recipients", False),
    # N'avoir aucun désabonné est parfaitement plausible.
    "config/unsubscribed.toml":   ("unsubscribed", True),
    "config/subscriber_ids.toml": ("subscriber_ids", True),
    # Refus de mesure : contient des adresses, et n'être refusé par personne
    # est plausible.
    "config/tracking_optout.toml": ("tracking_optout", True),
}


def _github_fetcher(repo: str, token: str, branch: str = "main") -> Callable[[str], Optional[str]]:
    """Téléchargeur GitHub. Retourne None si le fichier est absent (404)."""

    def fetch(path: str) -> Optional[str]:
        response = requests.get(
            f"https://api.github.com/repos/{repo}/contents/{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"ref": branch},
            timeout=15,
        )
        if response.status_code == 404:
            return None
        # Tout autre code d'erreur lève : un 401 ou un 403 ne doit surtout pas
        # être confondu avec « le fichier n'existe pas ».
        response.raise_for_status()
        return base64.b64decode(response.json()["content"].replace("\n", "")).decode("utf-8")

    return fetch


def _count_entries(content: str, path: str, section: str, may_be_empty: bool) -> int:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"{path} illisible depuis le dépôt de données : {exc}") from exc

    entries = data.get(section, {}).get("emails", [])
    if not entries and not may_be_empty:
        raise RuntimeError(
            f"{path} ne contient aucun destinataire. C'est plus probablement une "
            f"lecture partielle qu'un état réel — récupération interrompue."
        )
    return len(entries)


def fetch_subscriber_data(
    destination: Path,
    fetch: Callable[[str], Optional[str]],
) -> dict[str, int]:
    """
    Récupère et valide les trois fichiers, puis les écrit.

    Retourne {chemin: nombre d'entrées}. Lève si l'un manque, est illisible ou
    paraît tronqué — sans avoir rien écrit.
    """
    validated: dict[str, tuple[str, int]] = {}

    for path, (section, may_be_empty) in SUBSCRIBER_FILES.items():
        content = fetch(path)
        if content is None:
            raise RuntimeError(
                f"{path} absent du dépôt de données. Vérifier DATA_REPO et les "
                f"droits du jeton — récupération interrompue."
            )
        validated[path] = (content, _count_entries(content, path, section, may_be_empty))

    # Tout est validé : on écrit seulement maintenant.
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for path, (content, _) in validated.items():
        (destination / Path(path).name).write_text(content, encoding="utf-8")

    return {path: count for path, (_, count) in validated.items()}


def main() -> int:
    # Les variables viennent de l'environnement en CI, du .env en local.
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", default=str(CONFIG_DIR))
    args = parser.parse_args()

    repo = os.environ.get("DATA_REPO")
    token = os.environ.get("GIT_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not repo:
        logger.error("DATA_REPO n'est pas défini — impossible de récupérer les abonnés.")
        return 1
    if not token:
        logger.error(
            "DATA_REPO et GIT_TOKEN sont requis pour récupérer les abonnés.\n"
            "  DATA_REPO=yousmaaza/newsletter-data\n"
            "  GIT_TOKEN=<PAT à portée fine, accès Contents aux DEUX dépôts>\n"
            "À poser dans .env en local, dans les secrets du dépôt en CI."
        )
        return 1

    logger.info(f"Récupération des abonnés depuis {repo}...")
    try:
        report = fetch_subscriber_data(Path(args.destination), _github_fetcher(repo, token))
    except (RuntimeError, requests.RequestException) as exc:
        logger.error(f"❌ {exc}")
        return 1

    for path, count in report.items():
        logger.info(f"  {count:3} entrées — {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
