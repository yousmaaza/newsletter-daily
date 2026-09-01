"""
Assemblage des données du dashboard d'engagement.

Deux sources, deux rythmes :
  - l'historique lourd (100+ éditions, thèmes, assiduité) vient de
    data/dashboard.json, régénéré par la CI après chaque envoi ;
  - les chiffres de l'édition du jour sont relus en direct à chaque appel,
    pour que le dashboard reflète les ouvertures et clics au fil de l'eau.

Un cache mémoire court évite de marteler l'API GitHub quand la page est
rafraîchie toutes les minutes.
"""

from __future__ import annotations

import json
import logging
import time
import os
import tomllib
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from interactions import load_clicks, load_feedback, load_opens, load_reactions
from unsubscribe import _github_get_file

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # noqa: BLE001 — base tzdata absente de l'image : on reste en UTC
    logging.getLogger(__name__).warning("Europe/Paris indisponible, bascule en UTC")
    PARIS = timezone.utc

HISTORY_TTL = 300   # l'historique ne bouge qu'après un envoi
LIVE_TTL    = 45    # ouvertures et clics du jour
RUNS_TTL    = 120   # statut des workflows

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: int, producer):
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = producer()
    _cache[key] = (now, value)
    return value


def today_paris() -> str:
    return datetime.now(PARIS).date().isoformat()


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _load_history(github_token: str, github_repo: str) -> dict:
    def fetch():
        _, content = _github_get_file("data/dashboard.json", github_token, github_repo)
        if not content:
            raise FileNotFoundError(
                "data/dashboard.json est absent du dépôt. "
                "Lancer scripts/build_dashboard_data.py puis committer le résultat."
            )
        return json.loads(content)

    return _cached("history", HISTORY_TTL, fetch)


def _active_recipients(github_token: str, github_repo: str) -> int:
    def fetch():
        # Les listes d'abonnés vivent dans le dépôt PRIVÉ dédié (#55) ;
        # seules les mesures anonymes restent dans le dépôt applicatif.
        data_repo = os.environ.get("DATA_REPO") or github_repo

        def emails(path: str, key: str) -> set[str]:
            _, content = _github_get_file(path, github_token, data_repo)
            if not content:
                return set()
            data = tomllib.loads(content)
            return {e.strip().lower() for e in data.get(key, {}).get("emails", []) if e.strip()}

        recipients = emails("config/recipients.toml", "recipients")
        unsubscribed = emails("config/unsubscribed.toml", "unsubscribed")
        return len(recipients - unsubscribed)

    return _cached("recipients", HISTORY_TTL, fetch)


def _recent_runs(github_token: str, github_repo: str, limit: int = 40) -> list[dict]:
    def fetch():
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{github_repo}/actions/workflows/newsletter.yml/runs",
                headers={"Authorization": f"Bearer {github_token}",
                         "Accept": "application/vnd.github+json"},
                params={"per_page": limit}, timeout=10,
            )
            resp.raise_for_status()
            return [
                {"date": r["created_at"][:10], "at": r["created_at"][11:16],
                 "ok": r["conclusion"] == "success", "event": r["event"], "url": r["html_url"]}
                for r in resp.json().get("workflow_runs", [])
                if r["conclusion"] is not None
            ]
        except Exception as exc:  # noqa: BLE001 — on retombe sur l'historique figé
            logger.warning("Historique des runs indisponible : %s", exc)
            return []

    return _cached("runs", RUNS_TTL, fetch)


def _live_edition(send_date: str, sent: int, github_token: str, github_repo: str) -> dict:
    def fetch():
        opens     = load_opens(send_date, github_token, github_repo)
        clicks    = load_clicks(send_date, github_token, github_repo)
        feedback  = load_feedback(send_date, github_token, github_repo)
        reactions = load_reactions(send_date, github_token, github_repo)
        return {
            "date": send_date,
            "sent": sent,
            "opens": len({r["email_hash"] for r in opens}),
            "clicks": len(clicks),
            "clickers": len({r["email_hash"] for r in clicks}),
            "like":    sum(1 for r in feedback if r.get("global_reaction") == "like"),
            "meh":     sum(1 for r in feedback if r.get("global_reaction") == "meh"),
            "dislike": sum(1 for r in feedback if r.get("global_reaction") == "dislike"),
            "comments": [r["comment"] for r in feedback if r.get("comment", "").strip()],
            "art_reactions": len(reactions),
            "_clicks_rows": [{"rank": r["article_rank"], "url": r["target_url"]} for r in clicks],
            "_open_hours": [int(r["timestamp"][11:13]) for r in opens],
        }

    return _cached(f"live:{send_date}", LIVE_TTL, fetch)


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------

def build_payload(github_token: str, github_repo: str) -> dict:
    """Historique + édition du jour en direct, prêt à être injecté dans la page."""
    payload = json.loads(json.dumps(_load_history(github_token, github_repo)))  # copie
    send_date = today_paris()
    sent = _active_recipients(github_token, github_repo) or payload.get("current_sent", 0)
    # Copie : l'objet renvoyé par le cache ne doit pas être vidé de ses clés privées.
    live = dict(_live_edition(send_date, sent, github_token, github_repo))

    click_rows = live.pop("_clicks_rows")
    open_hours = live.pop("_open_hours")

    editions = payload.get("editions", [])
    previous = next((e for e in editions if e["date"] == send_date), None)

    if previous is None:
        # L'édition du jour n'est pas encore dans l'historique : on l'ajoute et on
        # reporte ses clics et ses ouvertures sur les agrégats.
        if live["opens"] or live["clicks"] or live["art_reactions"]:
            editions.append(live)
            _fold_in(payload, click_rows, open_hours)
    else:
        # Elle y est déjà mais avec les chiffres du dernier build : on remplace,
        # et on ajoute au global uniquement le delta observé depuis.
        delta_clicks = max(0, live["clicks"] - previous["clicks"])
        editions[editions.index(previous)] = live
        if delta_clicks:
            _fold_in(payload, click_rows[-delta_clicks:], [])

    payload["editions"] = sorted(editions, key=lambda e: e["date"])
    payload["current_sent"] = sent
    payload["totals"]["editions"] = len(payload["editions"])
    payload["totals"]["opens"] = sum(e["opens"] for e in payload["editions"])

    runs = _recent_runs(github_token, github_repo)
    if runs:
        payload["runs"] = runs

    payload["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["live"] = True
    return payload


def _fold_in(payload: dict, click_rows: list[dict], open_hours: list[int]) -> None:
    """Reporte des clics et ouvertures du jour sur les agrégats de l'historique."""
    by_rank = Counter({int(k): v for k, v in payload.get("by_rank", {}).items()})
    by_domain = Counter(payload.get("by_domain", {}))
    by_hour = Counter({int(k): v for k, v in payload.get("by_hour", {}).items()})

    for row in click_rows:
        by_rank[int(row["rank"])] += 1
        netloc = urlparse(row["url"]).netloc.replace("www.", "")
        if netloc:
            by_domain[netloc] += 1
    for hour in open_hours:
        by_hour[hour] += 1

    payload["by_rank"] = {str(k): by_rank[k] for k in sorted(by_rank)}
    payload["by_domain"] = dict(by_domain.most_common())
    payload["by_hour"] = {str(h): by_hour.get(h, 0) for h in range(24)}
    payload["totals"]["clicks"] = sum(by_rank.values())
