"""
Daily News Newsletter Agent
============================
Claude agent that uses Brave Search to find today's top 10 news,
generates a formatted HTML newsletter, and sends it via Gmail.

Uses Claude's tool_use (agent loop) to orchestrate the pipeline.
"""

import base64
import json
import logging
import os
from datetime import date
from pathlib import Path

import anthropic
import requests
from jinja2 import Template

from pydantic import ValidationError

from config import config, news_settings, prompts
from tools.brave_search import search_news
from tools.deduplicator import deduplicate_articles, deduplicate_newsletter_articles
from tools.gmail_tool import send_newsletter_email
from tools.newsletter_renderer import build_transparency_notice, render_for_recipient
from tools.newsletter_schema import NewsletterData
from tools.topic_memory import get_recent_topics, save_topics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (Claude tool_use schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "search_today_news",
        "description": (
            "Recherche les actualités du jour sur Internet via Brave Search. "
            "Retourne une liste d'articles avec titre, résumé, source et URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Thèmes à rechercher, ex: ['technologie', 'science', "
                        "'business', 'monde', 'santé']"
                    ),
                },
                "count": {
                    "type": "integer",
                    "description": "Nombre total d'articles à récupérer (défaut: 10)",
                    "default": 10,
                },
                "sites": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Domaines à inclure (ex: ['lemonde.fr', 'lefigaro.fr']). "
                        "Si absent, toutes les sources sont recherchées."
                    ),
                },
            },
            "required": ["topics"],
        },
    },
    {
        "name": "send_newsletter",
        "description": (
            "Envoie la newsletter par email via Gmail. "
            "Fournit les données structurées ; le HTML est généré automatiquement."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Sujet de l'email (titre de la newsletter)",
                },
                "newsletter_title": {
                    "type": "string",
                    "description": "Titre principal de la newsletter",
                },
                "intro": {
                    "type": "string",
                    "description": "Phrase d'introduction engageante",
                },
                "articles": {
                    "type": "array",
                    "description": "Liste des articles de la newsletter",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rank":   {"type": "integer", "description": "Rang (1-10)"},
                            "title":  {"type": "string",  "description": "Titre court et percutant (≤ 10 mots)"},
                            "flash":  {"type": "string",  "description": "1 phrase flash info style journaliste radio"},
                            "detail": {"type": "string",  "description": "2-3 phrases de contexte et analyse"},
                            "topic":  {"type": "string",  "description": "Thème (technologie, science, business, monde, santé)"},
                            "hype":   {"type": "string",  "enum": ["viral", "trending", "notable"], "description": "viral=breaking/explosif, trending=monte en puissance, notable=à savoir"},
                            "sources": {
                                "type": "array",
                                "description": "1-3 articles sources utilisés pour synthétiser cet item",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title":  {"type": "string", "description": "Titre de l'article source"},
                                        "url":    {"type": "string", "description": "URL de l'article source"},
                                        "source": {"type": "string", "description": "Nom de la publication"},
                                    },
                                    "required": ["title", "url", "source"],
                                },
                            },
                        },
                        "required": ["rank", "title", "flash", "detail", "topic", "hype", "sources"],
                    },
                },
                "conclusion": {
                    "type": "string",
                    "description": "Phrase de conclusion inspirante",
                },
            },
            "required": ["subject", "newsletter_title", "intro", "articles", "conclusion"],
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt() -> str:
    """Construit le system prompt avec les topics/count et la mémoire thématique."""
    recent = get_recent_topics(news_settings.topic_history_window_days)
    if recent:
        topics_history_section = (
            f"\n⚠️ Mémoire thématique ({news_settings.topic_history_window_days} derniers jours) :\n"
            f"Topics récemment couverts : {', '.join(recent)}\n"
            f"→ Privilégie des thèmes NON couverts récemment.\n"
            f"→ Si un topic récent domine l'actualité du jour, limite-le à 1 article maximum.\n"
        )
    else:
        topics_history_section = ""
    return prompts.system_prompt.format(
        topics=", ".join(news_settings.topics),
        count_per_topic=news_settings.count,
        newsletter_count=news_settings.newsletter_count,
        topics_history_section=topics_history_section,
    )

# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

def _execute_tool(
    tool_name: str,
    tool_input: dict,
    recipients_override: list[str] | None = None,
) -> str:
    """Execute a tool call and return the result as a JSON string."""
    if tool_name == "search_today_news":
        # Respecter le topic demandé par Claude, valider qu'il est dans la liste autorisée
        requested = tool_input.get("topics") or []
        allowed = set(news_settings.topics)
        topics = [t for t in requested if t in allowed] or news_settings.topics
        # count = articles par appel (défini dans la config, pas par Claude)
        count = news_settings.count
        sites  = news_settings.sites or None
        articles = search_news(topics=topics, count=count, sites=sites)
        if news_settings.dedup_enabled:
            articles = deduplicate_articles(articles, threshold=news_settings.dedup_similarity_threshold)
        return json.dumps(
            {
                "success": True,
                "count": len(articles),
                "articles": articles,
                "date": date.today().strftime("%d %B %Y"),
            },
            ensure_ascii=False,
        )

    elif tool_name == "send_newsletter":
        # Validate and coerce data with Pydantic (absorbs articles-as-string, rank coercion, etc.)
        try:
            newsletter = NewsletterData.model_validate(tool_input)
        except ValidationError as exc:
            error_msg = f"Données newsletter invalides : {exc}"
            logger.warning(error_msg)
            return json.dumps({"error": error_msg, "validation_errors": exc.errors()}, ensure_ascii=False)
        subject = newsletter.subject
        # Déduplication post-Claude sur les articles synthétisés
        validated_input = newsletter.model_dump()
        if news_settings.dedup_enabled:
            validated_input["articles"] = deduplicate_newsletter_articles(validated_input["articles"])
        # Sauvegarde des données de la newsletter
        _save_newsletter_data(validated_input)
        # Mise à jour de la mémoire thématique
        save_topics(validated_input["articles"], news_settings.topic_history_window_days)
        tool_input = validated_input
        send_date = date.today().strftime("%Y-%m-%d")

        def _render(recipient_email: str) -> str:
            # Un lecteur ayant refusé la mesure garde sa newsletter et son lien
            # de désinscription : seuls le pixel et les redirections disparaissent.
            measured = recipient_email.strip().lower() not in config.TRACKING_OPTOUT

            notice = None
            if config.SHOW_TRACKING_NOTICE and measured:
                notice = build_transparency_notice(
                    recipient_email,
                    send_date,
                    auth_server_url=config.AUTH_SERVER_URL,
                    secret=config.UNSUBSCRIBE_SECRET,
                    dashboard_url=config.DASHBOARD_PUBLIC_URL,
                    privacy_url=config.PRIVACY_URL,
                    subscriber_count=len(config.GMAIL_TO),
                )
            return render_for_recipient(
                tool_input,
                recipient_email,
                send_date,
                auth_server_url=config.AUTH_SERVER_URL,
                secret=config.UNSUBSCRIBE_SECRET,
                feedback_form_url=config.FEEDBACK_FORM_URL,
                transparency_notice=notice,
                tracking_enabled=measured,
            )

        result = send_newsletter_email(
            subject=subject,
            html_content="",
            get_html_for_recipient=_render,
            recipients_override=recipients_override,
        )

        # Un envoi réel s'inscrit au journal : c'est lui qui empêche une relance
        # de renvoyer l'édition (voir tools/sent_log.py). Un envoi de test ne
        # doit rien y écrire, sinon il condamnerait l'envoi réel du jour.
        if result.get("success") and recipients_override is None:
            from tools.sent_log import record_send
            record_send(date.today().strftime("%Y-%m-%d"), result.get("sent", 0))

        return json.dumps(result, ensure_ascii=False)

    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})


# ---------------------------------------------------------------------------
# Newsletter data persistence
# ---------------------------------------------------------------------------

def _save_newsletter_data(tool_input: dict) -> None:
    today_str = date.today().strftime("%Y-%m-%d")
    output_dir = Path(__file__).parent / "output" / "newsletter" / today_str
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / "data.json"
    data_path.write_text(json.dumps(tool_input, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Données newsletter sauvegardées : {data_path}")
    _push_newsletter_data_to_github(tool_input, today_str)


def _push_newsletter_data_to_github(tool_input: dict, send_date: str) -> None:
    """Pousse les articles (rank+title) sur GitHub pour que /feedback puisse les lire."""
    github_token = os.environ.get("GIT_TOKEN") or os.environ.get("GITHUB_TOKEN")
    github_repo  = os.environ.get("GITHUB_REPO") or (
        f"{os.environ.get('GIT_USERNAME','yousmaaza')}/{os.environ.get('GIT_REPO','newletter-ai')}"
    )
    if not github_token:
        logger.warning("GIT_TOKEN absent — articles non poussés sur GitHub")
        return

    slim = {
        "articles": [
            {"rank": a["rank"], "title": a.get("title", "")}
            for a in tool_input.get("articles", [])
        ]
    }
    content_b64 = base64.b64encode(json.dumps(slim, ensure_ascii=False).encode()).decode()
    path = f"output/newsletter/{send_date}/data.json"
    url  = f"https://api.github.com/repos/{github_repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Récupérer le SHA si le fichier existe déjà
    resp = requests.get(url, headers=headers, timeout=10)
    sha  = resp.json().get("sha") if resp.ok else None

    payload = {
        "message": f"data: newsletter articles {send_date} [skip ci]",
        "content": content_b64,
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    result = requests.put(url, headers=headers, json=payload, timeout=10)
    if result.ok:
        logger.info(f"Articles newsletter poussés sur GitHub : {path}")
    else:
        logger.warning(f"Push GitHub échoué ({result.status_code}): {result.text[:200]}")


# ---------------------------------------------------------------------------
# HTML template loader (Jinja2)
# ---------------------------------------------------------------------------

def _load_template() -> str:
    """Load and return the newsletter HTML template source."""
    template_path = Path(__file__).parent / "newsletter_template.html"
    return template_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

def run_agent(recipients_override: list[str] | None = None) -> None:
    """
    Run the daily newsletter agent.

    Claude orchestrates the full pipeline:
      search news → generate newsletter HTML → send email
    """
    logger.info("=== Daily News Agent started ===")
    today = date.today().strftime("%A %d %B %Y")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    initial_message = prompts.initial_message.format(today=today)

    messages = [{"role": "user", "content": initial_message}]

    # Agent loop
    max_iterations = 10
    for iteration in range(max_iterations):
        logger.info(f"Agent iteration {iteration + 1}")

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8096,
            system=_build_system_prompt(),
            tools=TOOLS,
            messages=messages,
        )

        logger.info(f"Stop reason: {response.stop_reason}")

        # Add assistant response to conversation
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            logger.info("Agent completed successfully.")
            break

        if response.stop_reason == "tool_use":
            # Process all tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"Calling tool: {block.name} with input: {json.dumps(block.input, ensure_ascii=False)[:200]}")
                    result = _execute_tool(block.name, block.input, recipients_override)
                    logger.info(f"Tool result (truncated): {result[:200]}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            messages.append({"role": "user", "content": tool_results})
        else:
            logger.warning(f"Unexpected stop reason: {response.stop_reason}")
            break
    else:
        logger.error("Agent reached max iterations without completing.")

    logger.info("=== Daily News Agent finished ===")
