"""
Renvoi de la table d'identifiants vers le dépôt de données privé (#55).

Un nouvel abonné reçoit son identifiant de mesure au moment de l'envoi, via
`SubscriberIds.get_or_create` — donc dans le runner GitHub Actions, qui est
éphémère. Sans ce renvoi, l'identifiant est perdu à la fin du job et la même
personne en reçoit un autre le lendemain : son historique de lecture se
fragmente en silence, et le compteur de lecteurs uniques gonfle sans raison.

Deux garde-fous :

  - **Rien n'est écrit si le contenu est identique.** C'est la leçon de #52 :
    l'API GitHub crée un commit même à contenu inchangé, et sans cette
    vérification chaque envoi en produirait un vide.

  - **Un fichier local plus petit que le distant est refusé.** La table ne
    devrait que grandir ; moins d'entrées signale une récupération ratée.
    Écraser effacerait des identifiants et orphelinerait l'historique de
    mesures des lecteurs concernés.

Usage :
    venv/bin/python scripts/push_subscriber_ids.py
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
IDS_PATH = ROOT / "config" / "subscriber_ids.toml"
REMOTE_PATH = "config/subscriber_ids.toml"

logger = logging.getLogger(__name__)


def _entry_count(content: str, origin: str) -> int:
    try:
        return len(tomllib.loads(content).get("subscriber_ids", {}).get("emails", []))
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Table d'identifiants illisible ({origin}) : {exc}") from exc


def push_subscriber_ids(
    local_path: Path,
    read_remote: Callable[[str], Optional[str]],
    write_remote: Callable[[str, str, str], None],
) -> bool:
    """
    Renvoie la table si elle a changé. Retourne True si une écriture a eu lieu.
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Table d'identifiants absente en local : {local_path}")

    local = local_path.read_text(encoding="utf-8")
    local_count = _entry_count(local, "local")

    remote = read_remote(REMOTE_PATH)
    if remote is not None:
        if local == remote:
            logger.info("Table d'identifiants inchangée — aucune écriture")
            return False
        if local_count < _entry_count(remote, "distant"):
            raise RuntimeError(
                f"La table locale a moins d'entrées que la distante "
                f"({local_count} contre {_entry_count(remote, 'distant')}). "
                f"Récupération probablement incomplète — écriture refusée."
            )

    write_remote(REMOTE_PATH, local, f"data: identifiants de mesure ({local_count}) [skip ci]")
    logger.info(f"Table d'identifiants renvoyée — {local_count} entrées")
    return True


# ---------------------------------------------------------------------------
# Transport GitHub
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_io(repo: str, token: str, branch: str = "main"):
    """Retourne (lecture, écriture) sur le dépôt de données."""
    base = f"https://api.github.com/repos/{repo}/contents"
    sha_holder: dict[str, str] = {}

    def read(path: str) -> Optional[str]:
        r = requests.get(f"{base}/{path}", headers=_headers(token),
                         params={"ref": branch}, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        payload = r.json()
        sha_holder[path] = payload["sha"]
        return base64.b64decode(payload["content"].replace("\n", "")).decode("utf-8")

    def write(path: str, content: str, message: str) -> None:
        body = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode(),
            "branch": branch,
        }
        if path in sha_holder:
            body["sha"] = sha_holder[path]
        r = requests.put(f"{base}/{path}", headers=_headers(token), json=body, timeout=15)
        r.raise_for_status()

    return read, write


def main() -> int:
    # Les variables viennent de l'environnement en CI, du .env en local.
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(IDS_PATH))
    args = parser.parse_args()

    repo = os.environ.get("DATA_REPO")
    token = os.environ.get("GIT_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        logger.error(
            "DATA_REPO et GIT_TOKEN sont requis pour renvoyer la table d'identifiants.\n"
            "  DATA_REPO=yousmaaza/newsletter-data\n"
            "  GIT_TOKEN=<PAT à portée fine, accès Contents aux DEUX dépôts>\n"
            "À poser dans .env en local, dans les secrets du dépôt en CI."
        )
        return 1

    read, write = _github_io(repo, token)
    try:
        push_subscriber_ids(Path(args.path), read, write)
    except (FileNotFoundError, RuntimeError, requests.RequestException) as exc:
        logger.error(f"❌ {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
