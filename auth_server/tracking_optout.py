"""
Refus de la mesure d'audience — côté serveur.

Action distincte de la désinscription : l'abonné continue de recevoir la
newsletter, seule la mesure s'arrête pour lui (pas de pixel, pas de
redirection de clic).

Le stockage calque `unsubscribe.py` : un TOML versionné sur GitHub, écrit via
l'API Contents avec la même boucle de retry.
"""

import hashlib
import hmac
import logging
import re
from datetime import date, datetime, timezone

from unsubscribe import _github_get_file, _github_put_with_retry  # même transport GitHub

logger = logging.getLogger(__name__)

OPTOUT_PATH = "config/tracking_optout.toml"
MAX_LINK_AGE_DAYS = 90


# ---------------------------------------------------------------------------
# Jeton signé
# ---------------------------------------------------------------------------

def generate_optout_token(email: str, send_date: str, secret: str) -> str:
    """
    HMAC-SHA256 de 'optout:email:send_date'.
    Doit rester identique à tools/unsubscribe_helper.py::generate_optout_token.

    Le préfixe rend le jeton inutilisable sur /unsubscribe, et réciproquement :
    un lien capté dans un email ne déclenche que l'action qu'il annonce.
    """
    payload = f"optout:{email.lower()}:{send_date}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_optout_token(
    email: str, send_date: str, token: str, secret: str, max_days: int = MAX_LINK_AGE_DAYS
) -> bool:
    """Vérifie le jeton en temps constant et rejette les liens trop anciens."""
    if not email or not send_date or not token or not secret:
        return False
    try:
        parsed = datetime.strptime(send_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    if (date.today() - parsed).days > max_days:
        return False
    return hmac.compare_digest(generate_optout_token(email, send_date, secret), token)


# ---------------------------------------------------------------------------
# Stockage TOML
# ---------------------------------------------------------------------------

def parse_optout_toml(content: str) -> dict[str, str]:
    """Extrait {email: iso_timestamp} depuis le contenu TOML."""
    emails_match = re.search(r"emails\s*=\s*\[([^\]]*)\]", content)
    if not emails_match or not emails_match.group(1).strip():
        return {}

    emails = [m.strip() for m in re.findall(r'"([^"]+)"', emails_match.group(1))]

    ts_match = re.search(r"timestamps\s*=\s*\[([^\]]*)\]", content)
    timestamps = (
        [m.strip() for m in re.findall(r'"([^"]+)"', ts_match.group(1))]
        if ts_match and ts_match.group(1).strip()
        else []
    )

    return {
        email: (timestamps[i] if i < len(timestamps) else "")
        for i, email in enumerate(emails)
    }


def build_optout_toml(entries: dict[str, str]) -> str:
    """Construit le TOML avec deux tableaux parallèles : emails et timestamps."""
    emails_line = ", ".join(f'"{e}"' for e in entries)
    timestamps_line = ", ".join(f'"{t}"' for t in entries.values())
    return (
        "# Adresses ayant refusé la mesure d'audience\n"
        "# Ces abonnés reçoivent toujours la newsletter : seuls le pixel et les\n"
        "# liens de redirection sont retirés de leur édition.\n"
        "# Mis à jour automatiquement par auth_server via /tracking-optout\n\n"
        "[tracking_optout]\n"
        f"emails     = [{emails_line}]\n"
        f"timestamps = [{timestamps_line}]\n"
    )


def apply_optout(current: str, email: str, now_iso: str) -> tuple[str, bool]:
    """
    Ajoute une adresse au contenu TOML fourni.

    Retourne (nouveau_contenu, était_nouveau). Si l'adresse est déjà présente,
    le contenu est renvoyé **inchangé** : un lien cliqué deux fois — ou suivi par
    un préchargeur d'email — ne produit aucun commit.
    """
    normalised = email.strip().lower()
    entries = parse_optout_toml(current)
    if normalised in {e.lower() for e in entries}:
        return current, False
    entries[normalised] = now_iso
    return build_optout_toml(entries), True


def add_to_tracking_optout(email: str, github_token: str, github_repo: str) -> bool:
    """
    Enregistre le refus de mesure dans config/tracking_optout.toml.
    Retourne True si l'adresse vient d'être ajoutée, False si elle y était déjà.

    L'état est lu AVANT d'écrire : sans cette lecture, le PUT part quand même et
    l'API GitHub crée un commit vide à contenu identique. Un lien recliqué — ou
    suivi par le préchargeur de liens d'un client mail — polluerait l'historique.
    """
    normalised = email.strip().lower()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _, current = _github_get_file(OPTOUT_PATH, github_token, github_repo)
    _, is_new = apply_optout(current or "", normalised, now_iso)

    if not is_new:
        logger.info(f"Refus de mesure déjà actif pour {normalised} — aucune écriture")
        return False

    def build(latest: str) -> str:
        # Relu dans la boucle de retry : le fichier a pu bouger entre-temps
        updated, _ = apply_optout(latest, normalised, now_iso)
        return updated

    _github_put_with_retry(
        OPTOUT_PATH,
        build,
        f"chore: tracking opt-out {normalised} [skip ci]",
        github_token,
        github_repo,
    )
    logger.info(f"Refus de mesure enregistré pour {normalised}")
    return True
