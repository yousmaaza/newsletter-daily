"""Gmail sending tool using Gmail API with OAuth2."""

import base64
import logging
import os
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Callable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _get_gmail_service():
    """Authenticate and return the Gmail API service."""
    creds = None
    token_path = Path(config.GMAIL_TOKEN_PATH)
    credentials_path = Path(config.GMAIL_CREDENTIALS_PATH)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                logger.error("Gmail token expired or revoked (invalid_grant). Sending re-auth email.")
                from tools.auth_notifier import send_reauth_email
                send_reauth_email()
                raise RuntimeError(
                    "Gmail token expired (invalid_grant).\n"
                    "  → En local : venv/bin/python scripts/reauth_local.py\n"
                    "  → En CI    : cliquer le lien dans l'email de re-auth reçu"
                ) from e
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {credentials_path}.\n"
                    "Download credentials.json from Google Cloud Console:\n"
                    "  1. Go to https://console.cloud.google.com\n"
                    "  2. Enable Gmail API\n"
                    "  3. Create OAuth2 credentials (Desktop app)\n"
                    "  4. Download and save as GMAIL_CREDENTIALS_PATH in .env"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        logger.info(f"Gmail token saved to {token_path}")

    return build("gmail", "v1", credentials=creds)


def build_mime_message(
    subject: str,
    sender: str,
    from_name: str,
    recipient: str,
    html: str,
    plain: str = "",
) -> MIMEMultipart:
    """Construit le message multipart/alternative de la newsletter."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), sender))
    msg["To"] = recipient
    if plain:
        msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def send_test_via_smtp(
    subject: str,
    recipient: str,
    html: str,
    plain: str = "",
) -> dict:
    """
    Envoie la newsletter à UNE adresse via SMTP + mot de passe d'application.

    Voie réservée aux envois de test : elle évite de dépendre de la chaîne OAuth
    complète, qui n'est pas toujours initialisée en local. Le même transport est
    déjà utilisé par tools/auth_notifier.py et auth_server/unsubscribe.py.
    """
    sender = config.GMAIL_FROM
    password = config.GMAIL_APP_PASSWORD
    if not sender:
        raise ValueError("GMAIL_FROM n'est pas configuré")
    if not password:
        raise ValueError(
            "GMAIL_APP_PASSWORD n'est pas configuré — requis pour l'envoi de test SMTP."
        )

    # resolve_recipients garantit qu'on ne peut pas viser la liste complète par erreur
    targets = resolve_recipients([recipient], config.GMAIL_TO)
    logger.warning(
        f"ENVOI DE TEST (SMTP) — {targets[0]} uniquement, la liste d'abonnés n'est PAS utilisée"
    )

    msg = build_mime_message(subject, sender, config.FROM_NAME, targets[0], html, plain)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(sender, password)
            smtp.sendmail(sender, targets, msg.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        raise ValueError(
            f"Authentification SMTP refusée pour {sender} — vérifier GMAIL_APP_PASSWORD "
            f"(mot de passe d'application, pas le mot de passe du compte). {exc}"
        ) from exc

    logger.info(f"✅ Email de test envoyé à {targets[0]}")
    return {"success": True, "sent": 1, "total": 1, "recipient": targets[0]}


def resolve_recipients(
    override: list[str] | None,
    configured: list[str],
) -> list[str]:
    """
    Détermine la liste d'envoi finale.

    `override` sert aux envois de test ciblés. Un override fourni mais vide est
    un bug d'appel : on lève plutôt que de retomber sur `configured`, sinon un
    « envoi de test » arroserait toute la liste d'abonnés.
    """
    if override is not None:
        cleaned = [addr.strip().lower() for addr in override if addr and addr.strip()]
        if not cleaned:
            raise ValueError(
                "Liste de destinataires de test vide — envoi interrompu "
                "(un override vide ne retombe jamais sur la liste complète)."
            )
        return cleaned

    cleaned = [addr.strip().lower() for addr in configured if addr and addr.strip()]
    if not cleaned:
        raise ValueError("Aucun destinataire configuré (config/recipients.toml ou GMAIL_TO).")
    return cleaned


def send_newsletter_email(
    subject: str,
    html_content: str,
    plain_content: str = "",
    get_html_for_recipient: Callable[[str], str] | None = None,
    recipients_override: list[str] | None = None,
) -> dict:
    """
    Send the newsletter via Gmail API.

    Args:
        subject: Email subject
        html_content: HTML body of the email
        plain_content: Plain text fallback (optional)

    Returns:
        dict with success status and message id
    """
    recipients = resolve_recipients(recipients_override, config.GMAIL_TO)
    sender = config.GMAIL_FROM

    if not sender:
        raise ValueError("GMAIL_FROM is not configured")

    if recipients_override is not None:
        logger.warning(
            f"ENVOI DE TEST — {len(recipients)} destinataire(s) : {', '.join(recipients)} "
            f"(la liste d'abonnés n'est PAS utilisée)"
        )

    results = []
    service = _get_gmail_service()

    for recipient in recipients:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{config.FROM_NAME} <{sender}>"
        msg["To"] = recipient

        body_html = get_html_for_recipient(recipient) if get_html_for_recipient else html_content
        if plain_content:
            msg.attach(MIMEText(plain_content, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        try:
            message = service.users().messages().send(userId="me", body={"raw": raw}).execute()
            logger.info(f"Newsletter sent to {recipient}. Message ID: {message['id']}")
            results.append({"recipient": recipient, "message_id": message["id"]})
        except HttpError as e:
            logger.error(f"Gmail API error for {recipient}: {e}")
            results.append({"recipient": recipient, "error": str(e)})

    success_count = sum(1 for r in results if "message_id" in r)
    error_count = len(recipients) - success_count
    logger.info(
        f"Newsletter envoyée : {success_count}/{len(recipients)} destinataire(s)"
        + (f" — {error_count} échec(s)" if error_count else "")
    )
    return {
        "success": success_count > 0,
        "sent": success_count,
        "total": len(recipients),
        "results": results,
    }
