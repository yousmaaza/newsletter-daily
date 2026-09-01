"""
Identifiants opaques des abonnés.

Remplace le SHA-256 non salé de l'adresse email utilisé jusqu'ici pour
identifier un lecteur dans les mesures. Un hash non salé n'est pas un
pseudonyme : à partir de la liste d'abonnés, il se retourne par simple
comparaison — 23 des 26 identifiants d'historique ont été ré-identifiés
en quelques millisecondes lors de l'audit du 25 août 2026.

Un identifiant tiré au sort n'a aucun lien calculable avec l'adresse. Il
apporte aussi le mécanisme d'effacement : supprimer une ligne de la table
suffit à rendre anonyme tout l'historique de mesures de la personne, sans
avoir à réécrire les fichiers de données.

⚠️ Le fichier vit dans `config/subscriber_ids.toml`, **séparé de
`recipients.toml`** : `scripts/sync_recipients.gs::buildToml_()` reconstruit
ce dernier entièrement à chaque soumission du formulaire d'inscription et
n'y écrit que le tableau `emails`. Un identifiant rangé là serait
silencieusement effacé au prochain inscrit.
"""

import logging
import re
import secrets
import tomllib
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

IDS_PATH = Path(__file__).parent.parent / "config" / "subscriber_ids.toml"

ID_BYTES = 16   # 32 caractères hexadécimaux


def new_identifier() -> str:
    """Identifiant aléatoire, sans lien avec quoi que ce soit d'autre."""
    return secrets.token_hex(ID_BYTES)


def parse_ids_toml(content: str) -> dict[str, str]:
    """Extrait {email: identifiant} depuis le contenu TOML."""
    if not content.strip():
        return {}
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        logger.error("config/subscriber_ids.toml illisible — table considérée vide")
        return {}

    section = data.get("subscriber_ids", {})
    emails = section.get("emails", [])
    ids = section.get("ids", [])
    return {
        email.strip().lower(): ids[i]
        for i, email in enumerate(emails)
        if i < len(ids) and email.strip()
    }


def build_ids_toml(entries: dict[str, str]) -> str:
    """Construit le TOML avec deux tableaux parallèles : emails et ids."""
    emails_line = ", ".join(f'"{e}"' for e in entries)
    ids_line = ", ".join(f'"{i}"' for i in entries.values())
    return (
        "# Correspondance entre abonnés et identifiants de mesure\n"
        "# Généré automatiquement — ne pas éditer à la main.\n"
        "#\n"
        "# Retirer une ligne rend anonyme tout l'historique de mesures de la\n"
        "# personne concernée : c'est le mécanisme d'effacement sur demande.\n"
        "#\n"
        "# Fichier SÉPARÉ de recipients.toml, que l'Apps Script d'inscription\n"
        "# reconstruit entièrement à chaque nouvel inscrit.\n\n"
        "[subscriber_ids]\n"
        f"emails = [{emails_line}]\n"
        f"ids    = [{ids_line}]\n"
    )


class SubscriberIds:
    """Table de correspondance adresse → identifiant opaque, persistée en TOML."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else IDS_PATH
        self._entries = parse_ids_toml(
            self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        )

    # ── Lecture ──────────────────────────────────────────────────────────

    def all_ids(self) -> dict[str, str]:
        """Copie de la table complète."""
        return dict(self._entries)

    def get(self, email: str) -> Optional[str]:
        return self._entries.get(email.strip().lower())

    # ── Écriture ─────────────────────────────────────────────────────────

    def get_or_create(self, email: str) -> str:
        """Identifiant de l'abonné, créé et persisté s'il est nouveau."""
        normalised = email.strip().lower()
        existing = self._entries.get(normalised)
        if existing:
            return existing

        identifier = new_identifier()
        self._entries[normalised] = identifier
        self._save()
        logger.info(f"Identifiant de mesure créé pour un nouvel abonné ({normalised})")
        return identifier

    def forget(self, email: str) -> bool:
        """
        Retire une adresse de la table.

        L'historique de mesures conserve l'identifiant mais devient orphelin :
        plus rien ne permet de le relier à une personne.
        Retourne True si l'adresse était présente.
        """
        normalised = email.strip().lower()
        if normalised not in self._entries:
            return False
        del self._entries[normalised]
        self._save()
        logger.info(f"Adresse retirée de la table d'identifiants ({normalised})")
        return True

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(build_ids_toml(self._entries), encoding="utf-8")
