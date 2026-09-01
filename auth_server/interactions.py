"""
Stockage des interactions newsletter (réactions, clics, ouvertures) en CSV GitHub.

Chaque type génère un fichier par jour :
  data/reactions_YYYY-MM-DD.csv
  data/clicks_YYYY-MM-DD.csv
  data/opens_YYYY-MM-DD.csv

Réutilise _github_put_with_retry et _github_get_file de unsubscribe.py.
"""

import csv
import hashlib
import hmac
import io
import logging
from datetime import datetime, timezone

from identifiers import normalise_identifier
from unsubscribe import _github_get_file, _github_put_with_retry

logger = logging.getLogger(__name__)

VALID_REACTIONS = frozenset({"like", "meh", "dislike"})

_REACTION_FIELDS  = ["timestamp", "email_hash", "article_rank", "reaction", "send_date"]
_CLICK_FIELDS     = ["timestamp", "email_hash", "article_rank", "target_url", "send_date"]
_OPEN_FIELDS      = ["timestamp", "email_hash", "send_date"]
_FEEDBACK_FIELDS  = ["timestamp", "email_hash", "send_date", "global_reaction", "comment"]


# ---------------------------------------------------------------------------
# HMAC validation (symétrique des helpers tools/interaction_helper.py)
# ---------------------------------------------------------------------------

def verify_interaction_token(
    email_hash: str, date_str: str, article_rank: str, token: str, secret: str
) -> bool:
    """Valide le token pour /react et /click (couvre email_hash:date:article_rank)."""
    if not all([email_hash, date_str, article_rank, token, secret]):
        return False
    payload = f"{email_hash}:{date_str}:{article_rank}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, token)


def verify_pixel_token(email_hash: str, date_str: str, token: str, secret: str) -> bool:
    """Valide le token pour /pixel (couvre email_hash:date)."""
    if not all([email_hash, date_str, token, secret]):
        return False
    payload = f"{email_hash}:{date_str}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, token)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _parse_csv(content: str, fieldnames: list) -> list[dict]:
    if not content.strip():
        return []
    return list(csv.DictReader(io.StringIO(content)))


def _build_csv(rows: list[dict], fieldnames: list) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, quoting=csv.QUOTE_ALL, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Réactions
# ---------------------------------------------------------------------------

def save_reaction(
    email_hash: str,
    send_date: str,
    article_rank: int,
    reaction: str,
    github_token: str,
    github_repo: str,
) -> bool:
    """Sauvegarde une réaction. Retourne True si nouveau, False si mise à jour (double-clic)."""
    # Voir save_open : les éditions déjà distribuées portent l'ancien
    # identifiant réversible dans leurs URL.
    email_hash = normalise_identifier(email_hash)
    path = f"data/reactions_{send_date}.csv"
    was_update = [False]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def build(current: str) -> str:
        rows = _parse_csv(current, _REACTION_FIELDS)
        existing = next(
            (r for r in rows if r.get("email_hash") == email_hash and str(r.get("article_rank")) == str(article_rank)),
            None,
        )
        if existing:
            was_update[0] = True
            existing["reaction"] = reaction
            existing["timestamp"] = now
        else:
            rows.append({
                "timestamp": now,
                "email_hash": email_hash,
                "article_rank": article_rank,
                "reaction": reaction,
                "send_date": send_date,
            })
        return _build_csv(rows, _REACTION_FIELDS)

    _github_put_with_retry(
        path, build,
        f"data: reaction {reaction} article={article_rank} [{send_date}] [skip ci]",
        github_token, github_repo,
    )
    return not was_update[0]


def load_reactions(send_date: str, github_token: str, github_repo: str) -> list[dict]:
    _, content = _github_get_file(f"data/reactions_{send_date}.csv", github_token, github_repo)
    return _parse_csv(content, _REACTION_FIELDS)


# ---------------------------------------------------------------------------
# Clics
# ---------------------------------------------------------------------------

def save_click(
    email_hash: str,
    send_date: str,
    article_rank: int,
    target_url: str,
    github_token: str,
    github_repo: str,
) -> None:
    # Voir save_open : les éditions déjà distribuées portent l'ancien
    # identifiant réversible dans leurs URL.
    email_hash = normalise_identifier(email_hash)
    path = f"data/clicks_{send_date}.csv"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def build(current: str) -> str:
        rows = _parse_csv(current, _CLICK_FIELDS)
        rows.append({
            "timestamp": now,
            "email_hash": email_hash,
            "article_rank": article_rank,
            "target_url": target_url,
            "send_date": send_date,
        })
        return _build_csv(rows, _CLICK_FIELDS)

    _github_put_with_retry(
        path, build,
        f"data: click article={article_rank} [{send_date}] [skip ci]",
        github_token, github_repo,
    )


def load_clicks(send_date: str, github_token: str, github_repo: str) -> list[dict]:
    _, content = _github_get_file(f"data/clicks_{send_date}.csv", github_token, github_repo)
    return _parse_csv(content, _CLICK_FIELDS)


# ---------------------------------------------------------------------------
# Ouvertures (pixel)
# ---------------------------------------------------------------------------

def save_open(email_hash: str, send_date: str, github_token: str, github_repo: str) -> None:
    """
    Enregistre une ouverture.

    L'identifiant est normalisé : les éditions déjà distribuées portent
    l'ancien hash réversible dans leur URL de pixel, et restent des mois dans
    les boîtes. Sans ce filtre, chaque ouverture d'une ancienne édition
    réintroduit une donnée ré-identifiable.

    L'état est lu avant d'écrire : sans cette lecture, une ouverture déjà
    enregistrée produit un commit vide. 15 sur 28 pour la seule journée du
    26 août 2026, cet endpoint étant le plus sollicité.
    """
    identifier = normalise_identifier(email_hash)
    path = f"data/opens_{send_date}.csv"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def build(current: str) -> str:
        rows = _parse_csv(current, _OPEN_FIELDS)
        if any(r.get("email_hash") == identifier for r in rows):
            return current  # idempotent — une seule ouverture par abonné
        rows.append({"timestamp": now, "email_hash": identifier, "send_date": send_date})
        return _build_csv(rows, _OPEN_FIELDS)

    _, current = _github_get_file(path, github_token, github_repo)
    if build(current or "") == (current or ""):
        logger.debug(f"Ouverture déjà enregistrée pour {send_date} — aucune écriture")
        return

    _github_put_with_retry(
        path, build,
        f"data: open [{send_date}] [skip ci]",
        github_token, github_repo,
    )


def load_opens(send_date: str, github_token: str, github_repo: str) -> list[dict]:
    _, content = _github_get_file(f"data/opens_{send_date}.csv", github_token, github_repo)
    return _parse_csv(content, _OPEN_FIELDS)


# ---------------------------------------------------------------------------
# Feedback global (réaction globale + commentaire)
# ---------------------------------------------------------------------------

def save_feedback(
    email_hash: str,
    send_date: str,
    global_reaction: str,
    comment: str,
    github_token: str,
    github_repo: str,
) -> None:
    email_hash = normalise_identifier(email_hash)
    path = f"data/feedback_{send_date}.csv"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def build(current: str) -> str:
        rows = _parse_csv(current, _FEEDBACK_FIELDS)
        existing = next((r for r in rows if r.get("email_hash") == email_hash), None)
        if existing:
            existing["global_reaction"] = global_reaction
            existing["comment"] = comment
            existing["timestamp"] = now
        else:
            rows.append({
                "timestamp": now,
                "email_hash": email_hash,
                "send_date": send_date,
                "global_reaction": global_reaction,
                "comment": comment,
            })
        return _build_csv(rows, _FEEDBACK_FIELDS)

    _github_put_with_retry(
        path, build,
        f"data: feedback global={global_reaction} [{send_date}] [skip ci]",
        github_token, github_repo,
    )


def load_feedback(send_date: str, github_token: str, github_repo: str) -> list[dict]:
    _, content = _github_get_file(f"data/feedback_{send_date}.csv", github_token, github_repo)
    return _parse_csv(content, _FEEDBACK_FIELDS)
