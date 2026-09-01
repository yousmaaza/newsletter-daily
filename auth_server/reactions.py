"""
Stockage des réactions newsletter dans data/reactions.json (via GitHub Contents API).
Réutilise les helpers GitHub de unsubscribe.py.
"""

import json
import logging
from datetime import datetime

from unsubscribe import _github_put_with_retry

logger = logging.getLogger(__name__)

_REACTIONS_PATH = "data/reactions.json"


def _parse_reactions(content: str) -> list[dict]:
    if not content.strip():
        return []
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("reactions.json corrompu, réinitialisé")
        return []


def save_event(
    event_type: str,
    email: str,
    send_date: str,
    github_token: str,
    github_repo: str,
    **kwargs,
) -> None:
    """
    Ajoute un event dans data/reactions.json.
    event_type : "open" | "reaction" | "rating"
    kwargs     : article_rank + reaction (pour "reaction"), stars (pour "rating")
    """
    entry = {
        "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "email": email.strip().lower(),
        "date": send_date,
        "type": event_type,
        **kwargs,
    }

    def build(current: str) -> str:
        events = _parse_reactions(current)
        events.append(entry)
        return json.dumps(events, ensure_ascii=False, indent=2)

    _github_put_with_retry(
        _REACTIONS_PATH,
        build,
        f"data: {event_type} from {email.strip().lower()} [{send_date}] [skip ci]",
        github_token,
        github_repo,
    )
    logger.info(f"Reaction saved: type={event_type} email={email} date={send_date} extra={kwargs}")
