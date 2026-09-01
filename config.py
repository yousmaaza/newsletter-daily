import logging
import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class NewsSettingsConfig:
    """Paramètres de recherche d'actualités (thèmes, sources) stockés dans config/news_settings.toml."""

    _SETTINGS_PATH = Path(__file__).parent / "config" / "news_settings.toml"

    def __init__(self):
        data = self._load()
        news = data.get("news", {})
        srcs = data.get("sources", {})

        # Topics : TOML en priorité, fallback env var pour migration
        self.topics: list[str] = news.get("topics") or [
            t.strip()
            for t in os.getenv("NEWS_TOPICS", "technologie,science,business,monde,santé").split(",")
            if t.strip()
        ]
        self.count: int = news.get("count") or int(os.getenv("NEWS_COUNT", "10"))
        self.sites: list[str] = srcs.get("sites", [])
        self.newsletter_count: int = news.get("newsletter_count", 10)
        self.presets: dict[str, list[str]] = data.get("source_presets", {})

        dedup = data.get("deduplication", {})
        self.dedup_enabled: bool = dedup.get("enabled", True)
        _threshold = float(dedup.get("similarity_threshold", 0.85))
        if not (0.7 <= _threshold <= 1.0):
            raise ValueError(
                f"deduplication.similarity_threshold doit être entre 0.7 et 1.0, reçu : {_threshold}"
            )
        self.dedup_similarity_threshold: float = _threshold

        topic_hist = data.get("topic_history", {})
        _window = int(topic_hist.get("window_days", 7))
        if not (1 <= _window <= 30):
            raise ValueError(
                f"topic_history.window_days doit être entre 1 et 30, reçu : {_window}"
            )
        self.topic_history_window_days: int = _window

    def _load(self) -> dict:
        if not self._SETTINGS_PATH.exists():
            return {}
        try:
            with open(self._SETTINGS_PATH, "rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Erreur de syntaxe dans config/news_settings.toml : {e}")

def _load_unsubscribed() -> set[str]:
    """Charge la liste des adresses désinscrites depuis config/unsubscribed.toml."""
    path = Path(__file__).parent / "config" / "unsubscribed.toml"
    if not path.exists():
        return set()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return {e.strip().lower() for e in data.get("unsubscribed", {}).get("emails", []) if e.strip()}
    except tomllib.TOMLDecodeError:
        logging.getLogger(__name__).warning("config/unsubscribed.toml corrompu — ignoré")
        return set()


def _load_tracking_optout() -> set[str]:
    """
    Charge les adresses ayant refusé la mesure d'audience.

    Ces abonnés restent destinataires : seuls le pixel et les liens de
    redirection sont retirés de leur édition. En cas de fichier illisible on
    retourne un ensemble vide — mais on le journalise en ERROR, car ignorer un
    refus silencieusement serait pire que de ne pas mesurer du tout.
    """
    path = Path(__file__).parent / "config" / "tracking_optout.toml"
    if not path.exists():
        return set()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        emails = data.get("tracking_optout", {}).get("emails", [])
        return {e.strip().lower() for e in emails if e.strip()}
    except tomllib.TOMLDecodeError:
        logging.getLogger(__name__).error(
            "config/tracking_optout.toml illisible — les refus de mesure ne peuvent pas "
            "être appliqués. Corriger le fichier avant le prochain envoi."
        )
        return set()


def _load_recipients() -> list[str]:
    """
    Charge la liste des destinataires depuis config/recipients.toml.
    Filtre les adresses présentes dans config/unsubscribed.toml.
    Fallback sur la variable d'environnement GMAIL_TO si le fichier est absent ou vide.
    """
    logger = logging.getLogger(__name__)
    recipients_path = Path(__file__).parent / "config" / "recipients.toml"
    if recipients_path.exists():
        try:
            with open(recipients_path, "rb") as f:
                data = tomllib.load(f)
            emails = data.get("recipients", {}).get("emails", [])
            if emails:
                cleaned = [e.strip() for e in emails if e.strip()]
                unsubscribed = _load_unsubscribed()
                if unsubscribed:
                    filtered = [e for e in cleaned if e.lower() not in unsubscribed]
                    if len(filtered) < len(cleaned):
                        logger.info(
                            f"{len(cleaned) - len(filtered)} adresse(s) filtrée(s) (désinscrites)"
                        )
                    cleaned = filtered
                logger.info(f"Destinataires chargés depuis recipients.toml : {len(cleaned)} adresse(s)")
                return cleaned
        except tomllib.TOMLDecodeError:
            logger.warning("config/recipients.toml corrompu — fallback sur GMAIL_TO")
    # Fallback : variable d'environnement
    emails = [
        addr.strip()
        for addr in os.getenv("GMAIL_TO", "").split(",")
        if addr.strip()
    ]
    logger.info(f"Destinataires chargés depuis GMAIL_TO (fallback) : {len(emails)} adresse(s)")
    return emails


class AppConfig:
    # Anthropic
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

    # Brave Search
    BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

    # Gmail — destinataires depuis config/recipients.toml (fallback: GMAIL_TO env var)
    GMAIL_FROM = os.getenv("GMAIL_FROM")
    GMAIL_TO: list[str] = _load_recipients()

    # Abonnés ayant refusé la mesure — ils reçoivent toujours la newsletter
    TRACKING_OPTOUT: set[str] = _load_tracking_optout()
    FROM_NAME = os.getenv("FROM_NAME", "Daily News Agent")
    GMAIL_CREDENTIALS_PATH = os.path.expanduser(os.getenv(
        "GMAIL_CREDENTIALS_PATH",
        "~/.gmail-mcp/credentials.json",
    ))
    GMAIL_TOKEN_PATH = os.path.expanduser(os.getenv(
        "GMAIL_TOKEN_PATH",
        "~/.gmail-mcp/token.json",
    ))

    def __init__(self):
        # Délègue à news_settings pour que les changements UI soient pris en compte
        self.NEWS_TOPICS: list[str] = news_settings.topics
        self.NEWS_COUNT: int = news_settings.count

    # Gmail re-auth (token expiry fallback)
    GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")   # Gmail App Password (not OAuth)
    AUTH_SERVER_URL = os.getenv("AUTH_SERVER_URL", "")     # Public URL of auth_server/

    # Newsletter — liens formulaires
    FEEDBACK_FORM_URL = os.getenv("FEEDBACK_FORM_URL", "")      # Formulaire de feedback post-lecture

    # Bloc transparence (mesure d'audience annoncée aux lecteurs)
    # Le bloc n'est rendu QUE si SHOW_TRACKING_NOTICE est vrai ET que les liens
    # d'action existent — voir tools/newsletter_renderer.py::_validated_transparency
    SHOW_TRACKING_NOTICE = os.getenv("SHOW_TRACKING_NOTICE", "").lower() in ("1", "true", "yes")
    # En CI, ces deux URL sont dérivées d'AUTH_SERVER_URL par concaténation.
    # Un slash final sur ce secret produirait « //board », que Flask renvoie
    # en 404 — soit un lien mort dans le bloc qui parle de confidentialité.
    DASHBOARD_PUBLIC_URL = os.getenv("DASHBOARD_PUBLIC_URL", "").replace("//board", "/board").rstrip("/")
    PRIVACY_URL          = os.getenv("PRIVACY_URL", "").replace("//vie-privee", "/vie-privee").rstrip("/")
    UNSUBSCRIBE_SECRET = os.getenv("UNSUBSCRIBE_SECRET", "")    # Secret HMAC pour les liens de désinscription

    # Scheduler
    SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "08:00")
    TIMEZONE = os.getenv("TIMEZONE", "Europe/Paris")

    def validate(self):
        missing = []
        if not self.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        if not self.BRAVE_API_KEY:
            missing.append("BRAVE_API_KEY")
        if not self.GMAIL_FROM:
            missing.append("GMAIL_FROM")
        if not self.GMAIL_TO:
            missing.append("GMAIL_TO (au moins une adresse requise)")
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


class PromptsConfig:
    def __init__(self):
        data = self._load()
        self.system_prompt: str   = data["newsletter"]["system_prompt"].strip()
        self.initial_message: str = data["newsletter"]["initial_message"].strip()

    @staticmethod
    def _load() -> dict:
        path = Path(__file__).parent / "config" / "prompts.toml"
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Fichier de prompts manquant : {path}\n"
                "Vérifier que config/prompts.toml existe."
            )
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Erreur de syntaxe dans config/prompts.toml : {e}")


news_settings = NewsSettingsConfig()
config  = AppConfig()
prompts = PromptsConfig()
