"""
Mémoire thématique glissante — évite la répétition inter-jours.
Stocke les topics couverts par édition dans output/topics_history.json.
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_HISTORY_PATH = Path(__file__).parent.parent / "output" / "topics_history.json"


def load_history() -> list[dict]:
    """Charge l'historique complet depuis topics_history.json."""
    if not _HISTORY_PATH.exists():
        return []
    try:
        return json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"topics_history.json illisible, ignoré : {exc}")
        return []


def purge_old_entries(history: list[dict], window_days: int) -> list[dict]:
    """Supprime les entrées plus anciennes que window_days jours."""
    cutoff = date.today() - timedelta(days=window_days)
    return [entry for entry in history if date.fromisoformat(entry["date"]) >= cutoff]


def get_recent_topics(window_days: int) -> list[str]:
    """Retourne les topics uniques couverts dans la fenêtre glissante (sans doublon)."""
    history = purge_old_entries(load_history(), window_days)
    seen: set[str] = set()
    topics: list[str] = []
    for entry in sorted(history, key=lambda e: e["date"], reverse=True):
        for t in entry.get("topics", []):
            if t not in seen:
                seen.add(t)
                topics.append(t)
    return topics


def save_topics(articles: list[dict], window_days: int) -> None:
    """Extrait les topics des articles générés et les ajoute à l'historique."""
    today_str = date.today().isoformat()
    topics = sorted({a["topic"] for a in articles if a.get("topic")})

    history = load_history()
    # Remplace l'entrée du jour si elle existe déjà (idempotent)
    history = [e for e in history if e["date"] != today_str]
    history.append({"date": today_str, "topics": topics})
    history = purge_old_entries(history, window_days)

    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Mémoire thématique mise à jour : {topics} (fenêtre {window_days}j)")
