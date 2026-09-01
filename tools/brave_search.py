"""Brave Search REST API wrapper for fetching news articles."""

import logging
import time
from datetime import date

import requests

from config import config

logger = logging.getLogger(__name__)

BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
BRAVE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"


_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = [2, 4, 8]  # secondes


def _get_with_retry(url: str, headers: dict, params: dict) -> requests.Response:
    """GET avec 3 tentatives et backoff exponentiel (2s, 4s, 8s)."""
    last_exc: Exception | None = None
    for attempt, wait in enumerate(zip(range(_RETRY_ATTEMPTS), _RETRY_BACKOFF), start=1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            last_exc = e
            _, delay = wait
            if attempt < _RETRY_ATTEMPTS:
                logger.debug(f"Tentative {attempt}/{_RETRY_ATTEMPTS} échouée ({e}), retry dans {delay}s…")
                time.sleep(delay)
    raise last_exc


def search_news(topics: list[str], count: int = 10, sites: list[str] | None = None) -> list[dict]:
    """
    Search for today's top news articles via Brave Search API.

    Args:
        topics: List of topics to search (e.g. ["technologie", "monde", "science"])
        count: Total number of articles to return
        sites: Optional list of domains to restrict results to (e.g. ["lemonde.fr", "lefigaro.fr"])

    Returns:
        List of articles with title, description, url, source, published_at
    """
    headers = {
        "X-Subscription-Token": config.BRAVE_API_KEY,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }

    articles: list[dict] = []
    seen_urls: set[str] = set()
    today_str = date.today().strftime("%d/%m/%Y")
    count_per_topic = max(3, count // len(topics))

    # Construit le filtre site: si des sources sont spécifiées
    site_filter = ""
    if sites:
        site_filter = "(" + " OR ".join(f"site:{s}" for s in sites) + ") "

    for topic in topics:
        if len(articles) >= count:
            break
        query = f"{site_filter}actualités {topic} {today_str}"
        try:
            response = _get_with_retry(
                BRAVE_NEWS_URL,
                headers=headers,
                params={
                    "q": query,
                    "count": count_per_topic,
                    "country": "FR",
                    "search_lang": "fr",
                    "freshness": "pd",  # past day
                },
            )
            data = response.json()

            for item in data.get("results", []):
                url = item.get("url")
                title = item.get("title", "").strip()
                description = item.get("description", "").strip()
                if not url or url in seen_urls or not title or not description:
                    continue
                seen_urls.add(url)
                articles.append(
                    {
                        "title": title,
                        "description": description,
                        "url": url,
                        "source": item.get("meta_url", {}).get("hostname", "Unknown"),
                        "published_at": item.get("age", today_str),
                        "topic": topic,
                        "thumbnail": item.get("thumbnail", {}).get("src"),
                    }
                )
                if len(articles) >= count:
                    break

        except requests.RequestException as e:
            logger.warning(f"Brave Search failed for topic '{topic}': {e}")

        # Respect Brave Search free-tier rate limit (1 req/s)
        time.sleep(1)

    # Fallback: general web search if not enough articles
    if len(articles) < count:
        try:
            response = _get_with_retry(
                BRAVE_WEB_URL,
                headers=headers,
                params={
                    "q": f"{site_filter}actualités du jour {today_str} France monde",
                    "count": count - len(articles),
                    "country": "FR",
                    "search_lang": "fr",
                    "freshness": "pd",
                },
            )
            data = response.json()
            for item in data.get("web", {}).get("results", []):
                url = item.get("url")
                title = item.get("title", "").strip()
                description = item.get("description", "").strip()
                if not url or url in seen_urls or not title or not description:
                    continue
                seen_urls.add(url)
                articles.append(
                    {
                        "title": title,
                        "description": description,
                        "url": url,
                        "source": item.get("meta_url", {}).get("hostname", "Unknown"),
                        "published_at": today_str,
                        "topic": "général",
                        "thumbnail": None,
                    }
                )
                if len(articles) >= count:
                    break
        except requests.RequestException as e:
            logger.warning(f"Brave Search fallback failed: {e}")

    logger.info(f"Brave Search returned {len(articles)} articles")
    return articles[:count]
