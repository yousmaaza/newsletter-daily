"""
Rendu HTML de la newsletter, par destinataire.

Extrait de la closure `_make_html_for_recipient` d'agent.py pour que le même
rendu soit réutilisable hors du pipeline d'envoi — prévisualisation locale,
envoi de test à une seule adresse, tests automatisés.

La configuration de suivi est **injectée** plutôt que lue depuis `config` :
un rendu sans `auth_server_url` ni `secret` ne contient aucune URL de mesure,
ce qui couvre à la fois la prévisualisation et les lecteurs ayant refusé le suivi.
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from jinja2 import Template
from pydantic import ValidationError

from tools.interaction_helper import (
    build_click_url,
    build_feedback_url,
    build_pixel_url,
)
from tools.newsletter_schema import NewsletterData
from tools.unsubscribe_helper import build_unsubscribe_url

TEMPLATE_PATH = Path(__file__).parent.parent / "newsletter_template.html"
DATA_ROOT = Path(__file__).parent.parent / "output" / "newsletter"
PREVIEW_DIR = Path(__file__).parent.parent / "output" / "preview"

PREVIEW_RECIPIENT = "apercu@exemple.local"

logger = logging.getLogger(__name__)

_FRENCH_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_FRENCH_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _load_template() -> Template:
    return Template(TEMPLATE_PATH.read_text(encoding="utf-8"))


def format_date_label(send_date: str) -> str:
    """2026-08-25 → 'mardi 25 août 2026' (sans dépendance à la locale système)."""
    try:
        year, month, day = (int(p) for p in send_date.split("-"))
        d = date(year, month, day)
        return f"{_FRENCH_DAYS[d.weekday()]} {day} {_FRENCH_MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return send_date


def _articles_with_click_urls(
    articles: list[dict], auth_server_url: str, recipient_email: str, send_date: str, secret: str
) -> list[dict]:
    """Réécrit chaque source avec son URL de redirection mesurée."""
    return [
        dict(
            article,
            sources=[
                dict(
                    source,
                    click_url=build_click_url(
                        auth_server_url, recipient_email, send_date,
                        article["rank"], source["url"], secret,
                    ),
                )
                for source in article.get("sources", [])
            ],
        )
        for article in articles
    ]


def _validated_transparency(notice: Optional[dict]) -> Optional[dict]:
    """
    N'autorise le bloc transparence que s'il est complet.

    Le bloc promet « voici comment refuser » : un bouton mort y ferait plus de
    dégâts que l'absence de bloc. On exige donc les deux liens d'action et les
    chiffres — `privacy_url` reste facultatif, sa ligne disparaît sans lui.
    """
    if not notice:
        return None

    required = ("tracking_optout_url", "dashboard_url", "stats")
    missing = [key for key in required if not notice.get(key)]
    if missing:
        logger.warning(
            f"Bloc transparence non rendu — éléments manquants : {', '.join(missing)}. "
            f"Un encart avec un lien mort est pire que pas d'encart."
        )
        return None
    return notice


def render_for_recipient(
    newsletter_data: dict,
    recipient_email: str,
    send_date: str,
    *,
    auth_server_url: Optional[str] = None,
    secret: Optional[str] = None,
    feedback_form_url: str = "",
    transparency_notice: Optional[dict] = None,
    tracking_enabled: bool = True,
) -> str:
    """
    Rend le corps HTML de la newsletter pour un destinataire donné.

    Sans `auth_server_url` et `secret`, le rendu ne contient ni pixel de mesure,
    ni liens de redirection : les sources pointent directement vers l'article.

    `tracking_enabled=False` coupe la mesure pour un lecteur qui l'a refusée,
    **sans toucher au lien de désinscription** : refuser d'être mesuré ne doit
    jamais retirer le moyen de partir.
    """
    server_configured = bool(auth_server_url and secret)
    measure = server_configured and tracking_enabled

    articles = newsletter_data.get("articles", [])
    unsubscribe_url = pixel_url = ""
    feedback_like_url = feedback_meh_url = feedback_dislike_url = ""

    if server_configured:
        unsubscribe_url = build_unsubscribe_url(auth_server_url, recipient_email, send_date, secret)

    if measure:
        pixel_url = build_pixel_url(auth_server_url, recipient_email, send_date, secret)
        feedback_like_url = build_feedback_url(
            auth_server_url, recipient_email, send_date, "like", secret)
        feedback_meh_url = build_feedback_url(
            auth_server_url, recipient_email, send_date, "meh", secret)
        feedback_dislike_url = build_feedback_url(
            auth_server_url, recipient_email, send_date, "dislike", secret)
        articles = _articles_with_click_urls(
            articles, auth_server_url, recipient_email, send_date, secret)

    return _load_template().render(
        newsletter_title=newsletter_data.get("newsletter_title", ""),
        today=format_date_label(send_date),
        intro=newsletter_data.get("intro", ""),
        articles=articles,
        conclusion=newsletter_data.get("conclusion", ""),
        feedback_form_url=feedback_form_url,
        unsubscribe_url=unsubscribe_url,
        pixel_url=pixel_url,
        feedback_like_url=feedback_like_url,
        feedback_meh_url=feedback_meh_url,
        feedback_dislike_url=feedback_dislike_url,
        transparency=_validated_transparency(transparency_notice),
    )


def build_transparency_notice(
    recipient_email: str,
    send_date: str,
    *,
    auth_server_url: str,
    secret: str,
    dashboard_url: str,
    privacy_url: str = "",
    subscriber_count: int = 0,
) -> Optional[dict]:
    """
    Assemble le bloc transparence pour un destinataire.

    Retourne None si un prérequis manque — le rendu s'en passera silencieusement
    plutôt que d'afficher un encart aux liens morts.
    """
    from tools.newsletter_stats import compute_transparency_stats
    from tools.unsubscribe_helper import build_tracking_optout_url

    if not (auth_server_url and secret and dashboard_url):
        return None

    return {
        "stats": compute_transparency_stats(subscriber_count=subscriber_count),
        "tracking_optout_url": build_tracking_optout_url(
            auth_server_url, recipient_email, send_date, secret),
        "dashboard_url": dashboard_url,
        "privacy_url": privacy_url,
    }


def require_transparency_notice(
    recipient_email: str,
    send_date: str,
    *,
    auth_server_url: str,
    secret: str,
    dashboard_url: str,
    privacy_url: str = "",
    subscriber_count: int = 0,
) -> dict:
    """
    Comme `build_transparency_notice`, mais lève si la configuration est incomplète.

    Utilisé quand le bloc est demandé explicitement (envoi de test) : recevoir un
    email sans le bouton qu'on voulait tester est pire qu'une erreur claire. Tous
    les manques sont listés d'un coup, pour ne pas les découvrir un par un.
    """
    missing = [
        name
        for name, value in (
            ("AUTH_SERVER_URL", auth_server_url),
            ("UNSUBSCRIBE_SECRET", secret),
            ("DASHBOARD_PUBLIC_URL", dashboard_url),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            f"Bloc transparence impossible — variable(s) manquante(s) : {', '.join(missing)}. "
            f"À renseigner dans .env avant de tester le bloc."
        )

    notice = build_transparency_notice(
        recipient_email,
        send_date,
        auth_server_url=auth_server_url,
        secret=secret,
        dashboard_url=dashboard_url,
        privacy_url=privacy_url,
        subscriber_count=subscriber_count,
    )
    if notice is None:  # pragma: no cover — les manques sont déjà couverts ci-dessus
        raise ValueError("Bloc transparence impossible — configuration incomplète.")
    return notice


def load_newsletter_data(
    send_date: str,
    data_root: Optional[Path] = None,
    data_file: Optional[Path] = None,
) -> dict:
    """
    Charge les données d'une newsletter, en vérifiant qu'elles sont complètes.

    Par défaut : output/newsletter/{date}/data.json. Le data.json versionné sur
    GitHub est une version allégée (rank + titre) poussée pour /feedback : elle
    ne suffit pas à composer une newsletter.

    `data_file` désigne un fichier explicite et l'emporte sur la date — la date
    ne sert alors qu'à l'affichage. C'est ce qui permet de valider un rendu
    depuis une édition de référence versionnée, sans lancer la génération.
    """
    if data_file is not None:
        path = Path(data_file)
        if not path.exists():
            raise FileNotFoundError(f"Fichier de données introuvable : {path}")
    else:
        root = data_root or DATA_ROOT
        path = root / send_date / "data.json"
        if not path.exists():
            raise FileNotFoundError(
                f"Aucune donnée newsletter pour le {send_date} ({path}). "
                f"Lance d'abord : python main.py --now"
            )

    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        NewsletterData.model_validate(data)
    except ValidationError as exc:
        missing = ", ".join(dict.fromkeys(str(err["loc"][0]) for err in exc.errors()))
        raise ValueError(
            f"Données newsletter incomplètes pour le {send_date} (champs manquants : {missing}). "
            f"Le data.json versionné sur GitHub ne contient que rank+title."
        ) from exc
    return data


def _preview_notice(subscriber_count: int) -> dict:
    """
    Bloc transparence pour la prévisualisation locale.

    Les liens configurés sont utilisés s'ils existent ; sinon on retombe sur des
    URL factices, ce qui reste sans danger — un aperçu ne quitte jamais la machine.
    """
    from tools.newsletter_stats import compute_transparency_stats

    placeholder = "https://exemple.local/lien-a-configurer"
    return {
        "stats": compute_transparency_stats(subscriber_count=subscriber_count),
        "tracking_optout_url": placeholder,
        "dashboard_url": placeholder,
        "privacy_url": placeholder,
    }


def write_preview(
    send_date: str,
    data_root: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    with_notice: bool = False,
) -> Path:
    """
    Rend la newsletter d'une date dans un fichier HTML local, sans rien envoyer.

    Le rendu est volontairement fait sans configuration de suivi : la
    prévisualisation ne contient donc aucun pixel ni lien de redirection, et
    peut être relancée autant de fois que nécessaire sans polluer les mesures.

    `with_notice` ajoute le bloc transparence pour l'inspecter visuellement.
    """
    data = load_newsletter_data(send_date, data_root)

    notice = None
    if with_notice:
        try:
            from config import config
            subscriber_count = len(config.GMAIL_TO)
        except Exception:  # noqa: BLE001 — l'aperçu ne doit pas dépendre du .env
            subscriber_count = 0
        notice = _preview_notice(subscriber_count)
        logger.warning(
            "Aperçu avec bloc transparence — les liens sont FACTICES. "
            "Configurer DASHBOARD_PUBLIC_URL et déployer /tracking-optout avant tout envoi."
        )

    html = render_for_recipient(data, PREVIEW_RECIPIENT, send_date, transparency_notice=notice)

    directory = out_dir or PREVIEW_DIR
    directory.mkdir(parents=True, exist_ok=True)
    out_path = directory / f"{send_date}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
