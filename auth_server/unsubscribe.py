"""
Logique de désinscription — côté auth_server.
Toutes les fonctions d'accès GitHub, TOML, CSV et notification email.
"""

import csv
import hashlib
import hmac
import io
import logging
import re
import smtplib
import time
from base64 import b64decode, b64encode
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

def generate_token(email: str, send_date: str, secret: str) -> str:
    """HMAC-SHA256 de 'email:send_date'. Identique à tools/unsubscribe_helper.py."""
    payload = f"{email.lower()}:{send_date}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_token(email: str, send_date: str, token: str, secret: str, max_days: int = 90) -> bool:
    """
    Vérifie le token HMAC en temps constant (résistant aux timing attacks).
    Rejette les tokens issus de newsletters vieilles de plus de `max_days` jours.
    """
    if not email or not send_date or not token or not secret:
        return False
    try:
        parsed_date = datetime.strptime(send_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    if (date.today() - parsed_date).days > max_days:
        return False
    expected = generate_token(email, send_date, secret)
    return hmac.compare_digest(expected, token)


# ---------------------------------------------------------------------------
# GitHub Contents API helpers
# ---------------------------------------------------------------------------

def _github_headers(github_token: str) -> dict:
    return {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_get_file(file_path: str, github_token: str, github_repo: str) -> tuple[str | None, str]:
    """
    Lit un fichier depuis GitHub.
    Retourne (sha, decoded_content) ou (None, "") si le fichier est absent.
    """
    url = f"https://api.github.com/repos/{github_repo}/contents/{file_path}"
    resp = requests.get(
        url,
        headers=_github_headers(github_token),
        params={"ref": "main"},
        timeout=10,
    )
    if resp.status_code == 404:
        return None, ""
    resp.raise_for_status()
    data = resp.json()
    sha = data.get("sha")
    content = b64decode(data["content"].replace("\n", "")).decode("utf-8")
    return sha, content


def _github_put_file(
    file_path: str,
    content: str,
    commit_msg: str,
    sha: str | None,
    github_token: str,
    github_repo: str,
) -> None:
    """Crée ou met à jour un fichier sur GitHub via l'API Contents."""
    url = f"https://api.github.com/repos/{github_repo}/contents/{file_path}"
    payload = {
        "message": commit_msg,
        "content": b64encode(content.encode("utf-8")).decode(),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    resp = requests.put(url, headers=_github_headers(github_token), json=payload, timeout=10)
    resp.raise_for_status()


def _github_put_with_retry(
    file_path: str,
    build_content_fn,
    commit_msg: str,
    github_token: str,
    github_repo: str,
    max_retries: int = 3,
) -> None:
    """
    PUT GitHub avec retry sur conflit SHA (409).
    `build_content_fn(current_content: str) -> str` calcule le nouveau contenu.
    """
    for attempt in range(max_retries):
        sha, current = _github_get_file(file_path, github_token, github_repo)
        new_content = build_content_fn(current)
        try:
            _github_put_file(file_path, new_content, commit_msg, sha, github_token, github_repo)
            return
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 409 and attempt < max_retries - 1:
                logger.warning(f"SHA conflict on {file_path}, retrying ({attempt + 1}/{max_retries})...")
                time.sleep(0.5)
                continue
            raise


# ---------------------------------------------------------------------------
# unsubscribed.toml helpers
# ---------------------------------------------------------------------------

def _parse_unsubscribed_toml(content: str) -> dict[str, str]:
    """
    Extrait {email: iso_timestamp} depuis le contenu TOML.
    Compatible avec l'ancien format (emails seuls) — timestamp vide dans ce cas.
    """
    emails_match = re.search(r'emails\s*=\s*\[([^\]]*)\]', content)
    if not emails_match or not emails_match.group(1).strip():
        return {}

    emails = [m.strip() for m in re.findall(r'"([^"]+)"', emails_match.group(1))]

    timestamps_match = re.search(r'timestamps\s*=\s*\[([^\]]*)\]', content)
    if timestamps_match and timestamps_match.group(1).strip():
        timestamps = [m.strip() for m in re.findall(r'"([^"]+)"', timestamps_match.group(1))]
    else:
        timestamps = []

    return {
        email: (timestamps[i] if i < len(timestamps) else "")
        for i, email in enumerate(emails)
    }


def _build_unsubscribed_toml(unsub_map: dict[str, str]) -> str:
    """Construit le TOML avec deux tableaux parallèles : emails et timestamps."""
    emails_line = ", ".join(f'"{e}"' for e in unsub_map)
    timestamps_line = ", ".join(f'"{t}"' for t in unsub_map.values())
    return (
        "# Liste des adresses désinscrites de la newsletter\n"
        "# Mis à jour automatiquement par auth_server via /unsubscribe\n\n"
        "[unsubscribed]\n"
        f"emails     = [{emails_line}]\n"
        f"timestamps = [{timestamps_line}]\n"
    )


def apply_unsubscribe(current: str, email: str, now_iso: str) -> tuple[str, bool]:
    """
    Ajoute une adresse au contenu TOML fourni.

    Retourne (nouveau_contenu, était_nouveau). Si l'adresse est déjà présente,
    le contenu revient **inchangé**.
    """
    normalised = email.strip().lower()
    entries = _parse_unsubscribed_toml(current)
    if normalised in {e.lower() for e in entries}:
        return current, False
    entries[normalised] = now_iso
    return _build_unsubscribed_toml(entries), True


def add_to_unsubscribed(email: str, github_token: str, github_repo: str) -> bool:
    """
    Ajoute l'email à config/unsubscribed.toml avec le timestamp UTC courant.
    Retourne True si ajouté, False s'il était déjà présent.

    L'état est lu AVANT d'écrire : sans cette lecture, le PUT part quand même
    et l'API GitHub crée un commit vide à contenu identique. Le déclencheur
    n'est pas le double clic humain mais le préchargeur de liens de certains
    clients mail, qui suit les URL sans intervention — chaque édition envoyée
    pouvait donc polluer l'historique de main. Voir #52.
    """
    email_lower = email.strip().lower()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _, current = _github_get_file("config/unsubscribed.toml", github_token, github_repo)
    _, is_new = apply_unsubscribe(current or "", email_lower, now_iso)

    if not is_new:
        logger.info(f"Déjà désinscrit : {email_lower} — aucune écriture")
        return False

    def build(latest: str) -> str:
        # Relu dans la boucle de retry : le fichier a pu bouger entre-temps
        updated, _ = apply_unsubscribe(latest, email_lower, now_iso)
        return updated

    _github_put_with_retry(
        "config/unsubscribed.toml",
        build,
        f"chore: unsubscribe {email_lower} [skip ci]",
        github_token,
        github_repo,
    )
    return True


# ---------------------------------------------------------------------------
# unsubscribe_reasons.csv helpers
# ---------------------------------------------------------------------------

def _ensure_csv_header(content: str) -> str:
    """Ajoute l'en-tête CSV si le fichier est vide."""
    if not content.strip():
        return "timestamp,send_date,reasons,free_text\n"
    return content


def append_reason_csv(
    email: str,
    send_date: str,
    reasons: list[str],
    free_text: str,
    github_token: str,
    github_repo: str,
) -> None:
    """
    Ajoute une ligne de motif dans data/unsubscribe_reasons.csv via l'API GitHub.

    **Aucune donnée identifiante n'est enregistrée.** Ce fichier sert à
    l'analyse agrégée des départs — `build_dashboard_data.py` n'en lit que
    `timestamp`, `reasons` et `free_text`. L'adresse y figurait sans usage.

    Le paramètre `email` est conservé dans la signature parce que les appelants
    le transmettent, mais il n'est ni écrit dans le fichier, ni dans le message
    de commit : un message de commit est définitif, une adresse y serait
    ineffaçable sans réécrire tout l'historique.
    """

    def build(current: str) -> str:
        content = _ensure_csv_header(current)
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            send_date,
            ";".join(reasons),
            free_text[:500],
        ])
        return content + buf.getvalue()

    _github_put_with_retry(
        "data/unsubscribe_reasons.csv",
        build,
        f"data: unsubscribe reason [{send_date}] [skip ci]",
        github_token,
        github_repo,
    )


# ---------------------------------------------------------------------------
# Notification email
# ---------------------------------------------------------------------------

def send_owner_notification(
    email: str,
    reasons: list[str],
    free_text: str,
    smtp_from: str,
    smtp_password: str,
) -> None:
    """
    Envoie un email de notification au propriétaire quand quelqu'un se désinscrit.
    Utilise SMTP avec GMAIL_APP_PASSWORD (pas OAuth).
    Non-bloquant : loggue l'erreur sans la remonter.
    """
    try:
        reasons_text = ", ".join(reasons) if reasons else "—"
        body = (
            f"Désinscription de la newsletter Daily News\n\n"
            f"Email : {email}\n"
            f"Date  : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Raisons : {reasons_text}\n"
        )
        if free_text:
            body += f"Commentaire : {free_text}\n"

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[Newsletter] Désinscription : {email}"
        msg["From"] = smtp_from
        msg["To"] = smtp_from  # notification envoyée au propriétaire (même adresse)

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(smtp_from, smtp_password)
            smtp.send_message(msg)

        logger.info(f"Notification de désinscription envoyée pour {email}")
    except Exception as e:
        logger.warning(f"Notification email échouée (non bloquant) : {e}")
