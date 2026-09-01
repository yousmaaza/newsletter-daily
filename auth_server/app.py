"""
Gmail OAuth Callback Server
============================
Tiny Flask app to be deployed on Railway / Render (free tier).

Flow:
  1. Newsletter agent detects invalid_grant → sends re-auth email
  2. User clicks the email button → GET /auth
  3. Redirected to Google OAuth consent screen
  4. Google redirects back → GET /callback?code=...
  5. Server exchanges code for tokens, updates GMAIL_TOKEN_JSON in GitHub Secrets
  6. User sees a success page; next newsletter run works automatically

Required environment variables (set in Railway/Render dashboard):
  GOOGLE_CLIENT_ID        — OAuth2 client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET    — OAuth2 client secret
  AUTH_SERVER_URL         — Public URL of this server (e.g. https://my-app.railway.app)
  GITHUB_TOKEN            — Fine-grained PAT with "secrets: write" on the repo
  GITHUB_REPO             — e.g. yousmaaza/newletter-ai
  UNSUBSCRIBE_SECRET      — Secret HMAC partagé avec le pipeline newsletter
  STATS_TOKEN             — Token d'accès au dashboard /stats/<date>
"""

import json
import logging
import os
import re
from base64 import b64decode, b64encode
from hmac import compare_digest
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
from flask import Flask, Response, redirect, render_template_string, request
from nacl import encoding, public

from dashboard_range import DEFAUT as RANGE_DEFAUT, RANGES, apply_range
from edition_detail import build_detail
from public_board import public_payload
from tracking_optout import add_to_tracking_optout, verify_optout_token
from unsubscribe import (
    add_to_unsubscribed,
    append_reason_csv,
    send_owner_notification,
    verify_token,
    _github_get_file,
)
try:
    from dashboard import build_payload as build_dashboard_payload
except Exception as _dashboard_exc:  # noqa: BLE001 — route facultative
    build_dashboard_payload = None
    logging.getLogger(__name__).warning(
        "Dashboard indisponible (%s) — les autres routes restent actives", _dashboard_exc
    )

from interactions import (
    VALID_REACTIONS,
    load_clicks,
    load_feedback,
    load_opens,
    load_reactions,
    save_click,
    save_feedback,
    save_open,
    save_reaction,
    verify_interaction_token,
    verify_pixel_token,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URI = "https://oauth2.googleapis.com/token"

# 1×1 transparent GIF
_PIXEL_GIF = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff"
    b"\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00\x00\x2c\x00\x00\x00\x00"
    b"\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
)


def _cfg(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


# ---------------------------------------------------------------------------
# GitHub Secrets helpers
# ---------------------------------------------------------------------------

def _get_repo_public_key() -> tuple[str, str]:
    resp = requests.get(
        f"https://api.github.com/repos/{_cfg('GITHUB_REPO')}/actions/secrets/public-key",
        headers={
            "Authorization": f"Bearer {_cfg('GITHUB_TOKEN')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["key_id"], data["key"]


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    pub_key = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pub_key).encrypt(secret_value.encode())
    return b64encode(sealed).decode()


def update_github_secret(secret_name: str, secret_value: str) -> None:
    key_id, pub_key_b64 = _get_repo_public_key()
    encrypted = _encrypt_secret(pub_key_b64, secret_value)
    resp = requests.put(
        f"https://api.github.com/repos/{_cfg('GITHUB_REPO')}/actions/secrets/{secret_name}",
        headers={
            "Authorization": f"Bearer {_cfg('GITHUB_TOKEN')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"encrypted_value": encrypted, "key_id": key_id},
        timeout=10,
    )
    resp.raise_for_status()
    logger.info(f"GitHub Secret '{secret_name}' updated successfully.")


# ---------------------------------------------------------------------------
# Routes — OAuth
# ---------------------------------------------------------------------------

@app.route("/auth")
def auth():
    client_id = _cfg("GOOGLE_CLIENT_ID")
    redirect_uri = f"{_cfg('AUTH_SERVER_URL').rstrip('/')}/callback"
    google_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}&redirect_uri={redirect_uri}"
        f"&response_type=code&scope={SCOPE}&access_type=offline&prompt=consent"
    )
    return redirect(google_url)


@app.route("/callback")
def callback():
    error = request.args.get("error")
    if error:
        return render_template_string(ERROR_PAGE, error=error), 400
    code = request.args.get("code")
    if not code:
        return render_template_string(ERROR_PAGE, error="Missing authorization code"), 400
    client_id = _cfg("GOOGLE_CLIENT_ID")
    client_secret = _cfg("GOOGLE_CLIENT_SECRET")
    redirect_uri = f"{_cfg('AUTH_SERVER_URL').rstrip('/')}/callback"
    try:
        token_resp = requests.post(TOKEN_URI, data={
            "code": code, "client_id": client_id, "client_secret": client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        }, timeout=10)
        token_resp.raise_for_status()
        tokens = token_resp.json()
    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        return render_template_string(ERROR_PAGE, error=f"Token exchange failed: {e}"), 500
    token_json = {
        "token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "token_uri": TOKEN_URI,
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": [SCOPE],
    }
    try:
        update_github_secret("GMAIL_TOKEN_JSON", json.dumps(token_json))
    except Exception as e:
        logger.error(f"GitHub Secret update failed: {e}")
        return render_template_string(ERROR_PAGE, error=f"Secret update failed: {e}"), 500
    return render_template_string(SUCCESS_PAGE)


# ---------------------------------------------------------------------------
# Routes — Unsubscribe
# ---------------------------------------------------------------------------

@app.route("/unsubscribe", methods=["GET"])
def unsubscribe_get():
    email = request.args.get("email", "").strip()
    date_str = request.args.get("date", "").strip()
    token = request.args.get("token", "").strip()
    if not email or not date_str or not token:
        return render_template_string(UNSUBSCRIBE_ERROR_PAGE, error="Paramètres manquants."), 400
    try:
        secret = _cfg("UNSUBSCRIBE_SECRET")
    except RuntimeError:
        return render_template_string(UNSUBSCRIBE_ERROR_PAGE, error="Service temporairement indisponible."), 503
    if not verify_token(email, date_str, token, secret):
        return render_template_string(UNSUBSCRIBE_ERROR_PAGE, error="Lien invalide ou expiré."), 400
    try:
        add_to_unsubscribed(email, _cfg("GITHUB_TOKEN"), _data_repo())
    except Exception as e:
        logger.error(f"Unsubscribe failed for {email}: {e}")
        return render_template_string(UNSUBSCRIBE_ERROR_PAGE, error="Erreur lors de la désinscription. Merci de réessayer."), 500
    return render_template_string(UNSUBSCRIBE_PAGE, email=email, date_str=date_str, token=token)


@app.route("/unsubscribe", methods=["POST"])
def unsubscribe_post():
    email = request.form.get("email", "").strip()
    date_str = request.form.get("date", "").strip()
    token = request.form.get("token", "").strip()
    try:
        secret = _cfg("UNSUBSCRIBE_SECRET")
    except RuntimeError:
        return render_template_string(UNSUBSCRIBE_ERROR_PAGE, error="Service temporairement indisponible."), 503
    if not verify_token(email, date_str, token, secret):
        return render_template_string(UNSUBSCRIBE_ERROR_PAGE, error="Lien invalide."), 400
    try:
        add_to_unsubscribed(email, _cfg("GITHUB_TOKEN"), _data_repo())
    except Exception as e:
        logger.warning(f"Re-unsubscribe check failed (non-blocking): {e}")
    reasons = request.form.getlist("reason")
    free_text = request.form.get("other", "").strip()[:500]
    try:
        append_reason_csv(email, date_str, reasons, free_text, _cfg("GITHUB_TOKEN"), _cfg("GITHUB_REPO"))
    except Exception as e:
        logger.warning(f"CSV append failed (non-blocking): {e}")
    try:
        send_owner_notification(email, reasons, free_text, _cfg("GMAIL_FROM"), _cfg("GMAIL_APP_PASSWORD"))
    except Exception as e:
        logger.warning(f"Owner notification failed (non-blocking): {e}")
    return render_template_string(REASON_CONFIRM_PAGE)


# ---------------------------------------------------------------------------
# Routes — Interactions (pixel / react / click)
# ---------------------------------------------------------------------------

@app.route("/tracking-optout", methods=["GET"])
def tracking_optout():
    """
    D&eacute;sactive la mesure d'audience pour un abonn&eacute;, sans le d&eacute;sabonner.

    Idempotent : un lien cliqu&eacute; deux fois &mdash; ou suivi par le pr&eacute;chargeur de
    liens d'un client mail &mdash; n'&eacute;crit rien la seconde fois.
    """
    email = request.args.get("email", "").strip()
    date_str = request.args.get("date", "").strip()
    token = request.args.get("token", "").strip()

    if not email or not date_str or not token:
        return render_template_string(UNSUBSCRIBE_ERROR_PAGE, error="Param\u00e8tres manquants."), 400

    try:
        secret = _cfg("UNSUBSCRIBE_SECRET")
    except RuntimeError:
        return render_template_string(
            UNSUBSCRIBE_ERROR_PAGE, error="Service temporairement indisponible."), 503

    if not verify_optout_token(email, date_str, token, secret):
        return render_template_string(
            UNSUBSCRIBE_ERROR_PAGE, error="Lien invalide ou expir\u00e9."), 400

    try:
        was_new = add_to_tracking_optout(email, _cfg("GITHUB_TOKEN"), _data_repo())
    except Exception as e:  # noqa: BLE001
        logger.error(f"Tracking opt-out failed for {email}: {e}")
        return render_template_string(
            UNSUBSCRIBE_ERROR_PAGE,
            error="Erreur lors de l'enregistrement. Merci de r\u00e9essayer."), 500

    return render_template_string(TRACKING_OPTOUT_PAGE, already=not was_new)


@app.route("/pixel")
def pixel():
    """Pixel de tracking d'ouverture email — 1×1 GIF transparent."""
    email_hash = request.args.get("email", "").strip()
    date_str   = request.args.get("date", "").strip()
    token      = request.args.get("token", "").strip()
    try:
        secret = _cfg("UNSUBSCRIBE_SECRET")
        if verify_pixel_token(email_hash, date_str, token, secret):
            save_open(email_hash, date_str, _cfg("GITHUB_TOKEN"), _cfg("GITHUB_REPO"))
    except Exception as e:
        logger.warning(f"Pixel save failed (non-blocking): {e}")
    return Response(_PIXEL_GIF, mimetype="image/gif",
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.route("/react")
def react():
    """Réaction emoji sur un article (👍 like / 😐 meh / 👎 dislike)."""
    email_hash   = request.args.get("email", "").strip()
    date_str     = request.args.get("date", "").strip()
    article_rank = request.args.get("article", "").strip()
    reaction     = request.args.get("r", "").strip()
    token        = request.args.get("token", "").strip()

    try:
        secret = _cfg("UNSUBSCRIBE_SECRET")
    except RuntimeError:
        return render_template_string(INTERACTION_ERROR_PAGE), 503

    if not verify_interaction_token(email_hash, date_str, article_rank, token, secret):
        return render_template_string(INTERACTION_ERROR_PAGE), 400

    if reaction not in VALID_REACTIONS or not article_rank.isdigit():
        return render_template_string(INTERACTION_ERROR_PAGE), 400

    try:
        is_new = save_reaction(
            email_hash, date_str, int(article_rank), reaction,
            _cfg("GITHUB_TOKEN"), _cfg("GITHUB_REPO"),
        )
    except Exception as e:
        logger.error(f"Reaction save failed: {e}")
        return render_template_string(INTERACTION_ERROR_PAGE), 500

    emoji_map = {"like": "👍", "meh": "😐", "dislike": "👎"}
    stats_url = f"{_cfg('AUTH_SERVER_URL').rstrip('/')}/stats/{date_str}"
    return render_template_string(
        REACTION_CONFIRM_PAGE,
        emoji=emoji_map[reaction],
        is_update=not is_new,
        stats_url=stats_url,
        send_date=date_str,
    )


@app.route("/click")
def click():
    """Tracking de clic sur un lien source — enregistre puis redirige."""
    email_hash   = request.args.get("email", "").strip()
    date_str     = request.args.get("date", "").strip()
    article_rank = request.args.get("article", "").strip()
    target_url   = request.args.get("url", "").strip()
    token        = request.args.get("token", "").strip()

    # Protection open redirect
    if not target_url.startswith(("http://", "https://")):
        return "Invalid URL", 400

    try:
        secret = _cfg("UNSUBSCRIBE_SECRET")
        if verify_interaction_token(email_hash, date_str, article_rank, token, secret) and article_rank.isdigit():
            save_click(
                email_hash, date_str, int(article_rank), target_url,
                _cfg("GITHUB_TOKEN"), _cfg("GITHUB_REPO"),
            )
    except Exception as e:
        logger.warning(f"Click save failed (non-blocking): {e}")

    return redirect(target_url, code=302)


# ---------------------------------------------------------------------------
# Route — Page feedback interactive (réactions par article + commentaire)
# ---------------------------------------------------------------------------

@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    """Page de feedback : réaction globale depuis l'email → page avec réactions par article + commentaire."""
    if request.method == "POST":
        email_hash      = request.form.get("email", "").strip()
        date_str        = request.form.get("date", "").strip()
        token           = request.form.get("token", "").strip()
        global_reaction = request.form.get("global", "").strip()
        comment         = request.form.get("comment", "").strip()
    else:
        email_hash      = request.args.get("email", "").strip()
        date_str        = request.args.get("date", "").strip()
        token           = request.args.get("token", "").strip()
        global_reaction = request.args.get("global", "").strip()
        comment         = ""

    try:
        secret = _cfg("UNSUBSCRIBE_SECRET")
    except RuntimeError:
        return render_template_string(INTERACTION_ERROR_PAGE), 503

    if not verify_pixel_token(email_hash, date_str, token, secret):
        return render_template_string(INTERACTION_ERROR_PAGE), 400

    try:
        github_token = _cfg("GITHUB_TOKEN")
        github_repo  = _cfg("GITHUB_REPO")
    except RuntimeError as e:
        return render_template_string(INTERACTION_ERROR_PAGE), 503

    if request.method == "POST":
        # Sauvegarde réaction globale + commentaire
        if global_reaction in VALID_REACTIONS:
            try:
                save_feedback(email_hash, date_str, global_reaction, comment, github_token, github_repo)
            except Exception as e:
                logger.error(f"Feedback save failed: {e}")

        # Sauvegarde réactions par article
        articles = _load_newsletter_articles(date_str, github_token, github_repo)
        for art in articles:
            rank = str(art.get("rank", ""))
            reaction = request.form.get(f"reaction_{rank}", "").strip()
            if reaction in VALID_REACTIONS:
                try:
                    save_reaction(email_hash, date_str, int(rank), reaction, github_token, github_repo)
                except Exception as e:
                    logger.error(f"Reaction save failed for article {rank}: {e}")

        return render_template_string(FEEDBACK_CONFIRM_PAGE)

    # GET — affiche le formulaire
    articles = _load_newsletter_articles(date_str, github_token, github_repo)
    return render_template_string(
        FEEDBACK_PAGE,
        email_hash=email_hash,
        date_str=date_str,
        token=token,
        global_reaction=global_reaction,
        articles=articles,
    )


# ---------------------------------------------------------------------------
# Route — Dashboard stats
# ---------------------------------------------------------------------------

def _load_recipients_count(github_token: str, github_repo: str) -> int:
    """Lit config/recipients.toml pour compter les abonnés actifs."""
    try:
        _, content = _github_get_file("config/recipients.toml", github_token, _data_repo())
        emails = re.findall(r'"([^"]+@[^"]+)"', content)
        return len(emails)
    except Exception:
        return 0


def _load_newsletter_articles(send_date: str, github_token: str, github_repo: str) -> list[dict]:
    """Lit output/newsletter/YYYY-MM-DD/data.json pour les titres des articles."""
    try:
        path = f"output/newsletter/{send_date}/data.json"
        _, content = _github_get_file(path, github_token, github_repo)
        if content:
            data = json.loads(content)
            return data.get("articles", [])
    except Exception:
        pass
    return []


@app.route("/stats/<send_date>")
def stats(send_date: str):
    """
    Ancienne page de détail d'édition, conservée en redirection.

    Elle disait la même chose que le tableau de bord, dans un autre style et
    avec sa propre authentification. Des liens circulent — une page qui
    disparaît sans rediriger est une page qui casse.
    """
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", send_date):
        return "Format de date invalide (AAAA-MM-JJ)", 400
    jeton, depuis_url = _jeton_fourni()
    reponse = redirect(f"/dashboard/{send_date}")
    if depuis_url:
        # Un vieux lien porte encore le jeton : on en profite pour ouvrir la
        # session, plutôt que de rediriger vers un refus.
        try:
            if compare_digest(jeton, _cfg("STATS_TOKEN")):
                return _pose_la_session(reponse, jeton)
        except RuntimeError:
            pass
    return reponse


DASHBOARD_TEMPLATE = Path(__file__).parent / "dashboard.html"
PRIVACY_TEMPLATE   = Path(__file__).parent / "vie_privee.html"
LANDING_TEMPLATE   = Path(__file__).parent / "landing.html"


# ---------------------------------------------------------------------------
# Session du tableau de bord
#
# Le jeton voyageait dans l'URL : barre d'adresse, historique, et toute
# capture d'écran. Il a fuité deux fois. Il a aussi produit un bogue
# bloquant — un lien « ?range=7d » remplaçait la chaîne de requête entière et
# emportait le jeton avec elle. Tant qu'un secret circule dans l'URL, chaque
# lien interne est une occasion de le perdre.
#
# On ouvre une fois avec ?token=, le serveur pose un cookie, et redirige vers
# une URL propre.
# ---------------------------------------------------------------------------

COOKIE_SESSION = "stats_session"
COOKIE_DUREE = 30 * 24 * 3600          # 30 jours


def _sur_https() -> bool:
    """Railway termine TLS en amont : le schéma vu par Flask est http."""
    return request.headers.get("X-Forwarded-Proto", request.scheme) == "https"


def _jeton_fourni() -> tuple[str, bool]:
    """Renvoie (jeton, vient_de_l_url). L'URL a priorité : c'est par elle qu'on ouvre une session."""
    depuis_url = request.args.get("token", "").strip()
    if depuis_url:
        return depuis_url, True
    return request.cookies.get(COOKIE_SESSION, ""), False


def _pose_la_session(reponse, jeton: str):
    reponse.set_cookie(
        COOKIE_SESSION, jeton,
        max_age=COOKIE_DUREE, httponly=True, secure=_sur_https(), samesite="Lax", path="/",
    )
    return reponse


def _dashboard_guard():
    """Contrôle d'accès partagé par /dashboard, /dashboard/data et /stats.

    Retourne (credentials, None) si l'accès est accordé, sinon (None, response)
    où response est la réponse de refus à renvoyer telle quelle.
    """
    if build_dashboard_payload is None:
        return None, ("Dashboard indisponible sur ce déploiement", 503)
    try:
        stats_token = _cfg("STATS_TOKEN")
    except RuntimeError:
        return None, ("STATS_TOKEN non configuré", 503)
    jeton, _ = _jeton_fourni()
    if not compare_digest(jeton, stats_token):
        return None, (render_template_string(STATS_AUTH_PAGE, send_date="dashboard"), 401)
    try:
        return (_cfg("GITHUB_TOKEN"), _cfg("GITHUB_REPO")), None
    except RuntimeError as exc:
        return None, (str(exc), 503)


def _detail_edition(send_date: str, github_token: str, github_repo: str) -> dict | None:
    """
    Détail d'une édition, ou None si on n'a pas pu le charger.

    Un détail manquant ne doit pas emporter la page : le reste du tableau de
    bord n'en dépend pas, et une vue d'ensemble amputée est plus utile qu'une
    erreur 502.
    """
    try:
        return build_detail(
            send_date=send_date,
            sent=_load_recipients_count(github_token, github_repo),
            opens=load_opens(send_date, github_token, github_repo),
            reactions=load_reactions(send_date, github_token, github_repo),
            clicks=load_clicks(send_date, github_token, github_repo),
            feedbacks=load_feedback(send_date, github_token, github_repo),
            articles=_load_newsletter_articles(send_date, github_token, github_repo),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Détail de l'édition %s indisponible", send_date)
        return None


@app.route("/dashboard")
@app.route("/dashboard/<send_date>")
def dashboard(send_date: str | None = None):
    """Tableau de bord, avec le détail d'une édition quand une date est donnée."""
    if send_date is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", send_date):
        return "Format de date invalide (AAAA-MM-JJ)", 400
    credentials, refusal = _dashboard_guard()
    if refusal:
        return refusal

    # Le jeton vient d'arriver par l'URL : on le range dans un cookie et on
    # renvoie vers une adresse propre. La période est conservée, sans quoi un
    # lien partagé sur « 3 mois » retomberait sur « tout ».
    jeton, depuis_url = _jeton_fourni()
    if depuis_url:
        periode = request.args.get("range", "")
        cible = f"/dashboard/{send_date}" if send_date else "/dashboard"
        cible += f"?range={periode}" if periode in RANGES else ""
        return _pose_la_session(redirect(cible), jeton)

    github_token, github_repo = credentials

    try:
        payload = build_dashboard_payload(github_token, github_repo)
    except FileNotFoundError as exc:
        return str(exc), 503
    except Exception as exc:  # noqa: BLE001
        logger.exception("Construction du dashboard impossible")
        return f"Données indisponibles : {exc}", 502

    # Une période inconnue rend le payload complet plutôt qu'une page vide :
    # un paramètre d'URL trafiqué ne doit pas ressembler à une absence de données.
    payload = apply_range(payload, request.args.get("range", RANGE_DEFAUT))

    # L'édition demandée, ou la plus récente de la période affichée.
    editions = payload.get("editions") or []
    cible = send_date or (editions[-1]["date"] if editions else None)
    if cible:
        payload["edition"] = _detail_edition(cible, github_token, github_repo)

    try:
        template = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        return "dashboard.html introuvable sur le serveur", 500

    html = template.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    return Response(html, mimetype="text/html",
                    headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@app.route("/dashboard/data")
def dashboard_data():
    """Payload JSON consommé par le rafraîchissement automatique de la page."""
    credentials, refusal = _dashboard_guard()
    if refusal:
        return refusal
    github_token, github_repo = credentials

    try:
        payload = apply_range(
            build_dashboard_payload(github_token, github_repo),
            request.args.get("range", RANGE_DEFAUT),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Rafraîchissement du dashboard impossible")
        return {"error": str(exc)}, 502

    return Response(json.dumps(payload, ensure_ascii=False), mimetype="application/json",
                    headers={"Cache-Control": "no-store"})


@app.route("/board")
def public_board():
    """
    Tableau de bord public, sans jeton.

    Sert les mêmes agrégats que /dashboard, filtrés par une liste blanche
    (voir public_board.py). Indexable : c'est la page que la newsletter
    annonce à ses lecteurs.
    """
    if build_dashboard_payload is None:
        return "Tableau de bord temporairement indisponible", 503
    try:
        github_token, github_repo = _cfg("GITHUB_TOKEN"), _cfg("GITHUB_REPO")
    except RuntimeError:
        return "Tableau de bord temporairement indisponible", 503

    try:
        payload = public_payload(build_dashboard_payload(github_token, github_repo))
    except Exception:  # noqa: BLE001
        logger.exception("Construction du tableau de bord public impossible")
        return "Données temporairement indisponibles", 502

    try:
        template = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        return "dashboard.html introuvable sur le serveur", 500

    html = template.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    # Pas de X-Robots-Tag : cette page a vocation à être trouvée.
    return Response(html, mimetype="text/html",
                    headers={"Cache-Control": "public, max-age=300"})


@app.route("/board/data")
def public_board_data():
    """Payload JSON public, filtré par la même liste blanche."""
    if build_dashboard_payload is None:
        return {"error": "indisponible"}, 503
    try:
        github_token, github_repo = _cfg("GITHUB_TOKEN"), _cfg("GITHUB_REPO")
    except RuntimeError:
        return {"error": "indisponible"}, 503

    try:
        payload = public_payload(build_dashboard_payload(github_token, github_repo))
    except Exception:  # noqa: BLE001
        logger.exception("Rafraîchissement du tableau de bord public impossible")
        return {"error": "indisponible"}, 502

    return Response(json.dumps(payload, ensure_ascii=False), mimetype="application/json",
                    headers={"Cache-Control": "public, max-age=300"})


def _data_repo() -> str:
    """
    Dépôt hébergeant les données d'abonnés.

    Les fichiers de `config/` — destinataires, désinscrits, identifiants,
    refus de mesure — portent des adresses et vivent dans un dépôt PRIVÉ
    dédié, pour que le dépôt applicatif puisse être ouvert (#55).

    Ceux de `data/` sont anonymes depuis la migration vers les identifiants
    opaques et restent dans le dépôt applicatif : ce sont eux qui alimentent
    le tableau de bord public.

    Repli sur GITHUB_REPO tant que DATA_REPO n'est pas posé, pour que la
    transition ne casse rien.
    """
    return os.environ.get("DATA_REPO") or _cfg("GITHUB_REPO")


@app.route("/vie-privee")
def privacy_page():
    """
    Page d'information sur la mesure d'audience.

    Publique, indexable, et volontairement sans aucune dépendance : ni jeton,
    ni GitHub, ni données. Une page qui explique aux lecteurs ce qui est
    collecté ne doit pas tomber avec l'infrastructure qu'elle décrit.
    """
    try:
        html = PRIVACY_TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        logger.exception("vie_privee.html introuvable sur le serveur")
        return "Page temporairement indisponible", 500

    return Response(html, mimetype="text/html",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.route("/inscription")
def landing_page():
    """
    Page d'inscription publique.

    Le formulaire poste directement vers Google Forms : la réponse atterrit
    dans la Sheet et déclenche `onFormSubmit`, donc `sync_recipients.gs`
    déduplique, filtre les désinscrits et met à jour recipients.toml comme
    pour n'importe quelle inscription. Rien n'est écrit ici — cette route ne
    fait que servir un fichier.

    Le garde-fou du placeholder n'est pas du zèle : le navigateur ne peut pas
    lire la réponse de Google (pas d'en-tête CORS), donc la page confirme
    l'inscription sans preuve. Servie avec un FORM_ID non remplacé, elle
    remercierait chaque visiteur tout en jetant son adresse. Mieux vaut une
    page absente qu'une page qui ment.
    """
    try:
        html = LANDING_TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        logger.exception("landing.html introuvable sur le serveur")
        return "Page temporairement indisponible", 500

    if "/e/FORM_ID/" in html:
        logger.error(
            "landing.html n'est pas configurée : FORM_ID et les identifiants "
            "entry.* doivent être remplacés par ceux du Google Form."
        )
        return "Page d'inscription non configurée", 503

    return Response(html, mimetype="text/html",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.route("/health")
def health():
    return {"status": "ok"}, 200


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------

SUCCESS_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Authentification réussie</title></head>
<body style="margin:0;padding:40px;background:#f4f4f4;font-family:sans-serif;text-align:center;">
  <div style="max-width:480px;margin:80px auto;background:#fff;border-radius:8px;
              padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
    <div style="font-size:48px;margin-bottom:16px;">✅</div>
    <h1 style="color:#1c1917;margin:0 0 12px;">Authentification réussie !</h1>
    <p style="color:#57534e;line-height:1.6;">
      Le token Gmail a été renouvelé et mis à jour dans GitHub Actions.<br>
      La prochaine newsletter sera envoyée normalement.
    </p>
    <p style="color:#a8a29e;font-size:13px;margin-top:24px;">Vous pouvez fermer cette fenêtre.</p>
  </div>
</body>
</html>"""

UNSUBSCRIBE_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><title>Désinscription confirmée</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:40px;background:#faf8f4;font-family:sans-serif;text-align:center;">
  <div style="max-width:520px;margin:60px auto;background:#fff;border-radius:8px;
              padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <div style="font-size:48px;margin-bottom:16px;">👋</div>
    <h1 style="color:#1c1917;margin:0 0 12px;font-size:22px;">Vous avez été désinscrit(e)</h1>
    <p style="color:#57534e;line-height:1.6;margin:0 0 28px;">
      L'adresse <strong>{{ email }}</strong> ne recevra plus la newsletter Daily News.
    </p>
    <hr style="border:none;border-top:1px solid #e7e5e4;margin:0 0 28px;">
    <p style="color:#78716c;font-size:14px;font-weight:600;margin:0 0 16px;text-align:left;">
      Pourquoi partez-vous ? <span style="font-weight:400;color:#a09080;">(optionnel)</span>
    </p>
    <form method="POST" action="/unsubscribe" style="text-align:left;">
      <input type="hidden" name="email" value="{{ email }}">
      <input type="hidden" name="date"  value="{{ date_str }}">
      <input type="hidden" name="token" value="{{ token }}">
      {% set reasons = [
        ("too_frequent", "Trop d'emails"),
        ("irrelevant",   "Contenu pas pertinent pour moi"),
        ("never_signed", "Je ne me souviens pas m'être inscrit(e)"),
        ("too_long",     "Les emails sont trop longs"),
        ("other",        "Autre raison")
      ] %}
      {% for value, label in reasons %}
      <label style="display:flex;align-items:center;gap:10px;margin-bottom:12px;cursor:pointer;color:#44403c;font-size:14px;">
        <input type="checkbox" name="reason" value="{{ value }}" style="width:16px;height:16px;cursor:pointer;"
               {% if value == 'other' %}onclick="document.getElementById('other-block').style.display=this.checked?'block':'none'"{% endif %}>
        {{ label }}
      </label>
      {% endfor %}
      <div id="other-block" style="display:none;margin:4px 0 16px 26px;">
        <textarea name="other" rows="3" maxlength="500" placeholder="Dites-nous en plus..."
                  style="width:100%;box-sizing:border-box;padding:10px;border:1px solid #d6d3d1;
                         border-radius:6px;font-size:13px;color:#44403c;resize:vertical;font-family:sans-serif;"></textarea>
      </div>
      <div style="margin-top:20px;display:flex;gap:12px;justify-content:flex-end;">
        <a href="/" style="padding:10px 20px;border:1px solid #d6d3d1;border-radius:6px;font-size:13px;color:#78716c;text-decoration:none;">Passer</a>
        <button type="submit" style="padding:10px 24px;background:#c9001e;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">Envoyer mon avis</button>
      </div>
    </form>
  </div>
</body>
</html>"""

TRACKING_OPTOUT_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mesure d&eacute;sactiv&eacute;e</title></head>
<body style="margin:0;padding:40px;background:#faf8f4;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:520px;margin:60px auto;background:#fff;border-radius:8px;
              border-top:3px solid #c9001e;padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <p style="margin:0 0 10px;font-size:10px;font-weight:700;letter-spacing:3px;
              text-transform:uppercase;color:#c9001e;">C&rsquo;EST FAIT</p>
    <h1 style="color:#1c1917;margin:0 0 16px;font-family:Georgia,serif;font-size:26px;
               line-height:1.25;">Vous n&rsquo;&ecirc;tes plus mesur&eacute;</h1>
    <p style="color:#3d3530;line-height:1.65;margin:0 0 14px;font-size:15px;">
      &Agrave; partir de la prochaine &eacute;dition, vos ouvertures et vos clics ne sont plus
      enregistr&eacute;s. <strong>Vous restez abonn&eacute;</strong> &mdash; la newsletter continue
      d&rsquo;arriver normalement.
    </p>
    <p style="color:#57534e;line-height:1.65;margin:0 0 14px;font-size:14px;">
      Les mesures d&eacute;j&agrave; collect&eacute;es vous concernant peuvent &ecirc;tre supprim&eacute;es sur
      simple demande, en r&eacute;pondant &agrave; n&rsquo;importe quelle &eacute;dition.
    </p>
    {% if already %}
    <p style="color:#a09080;font-size:13px;margin:20px 0 0;padding-top:16px;
              border-top:1px solid #ede8df;">
      Ce refus &eacute;tait d&eacute;j&agrave; actif &mdash; rien n&rsquo;a chang&eacute;.
    </p>
    {% endif %}
    <p style="color:#a8a29e;font-size:13px;margin:24px 0 0;">Vous pouvez fermer cette fen&ecirc;tre.</p>
  </div>
</body>
</html>"""

REASON_CONFIRM_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Merci pour votre retour</title></head>
<body style="margin:0;padding:40px;background:#faf8f4;font-family:sans-serif;text-align:center;">
  <div style="max-width:480px;margin:80px auto;background:#fff;border-radius:8px;
              padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <div style="font-size:48px;margin-bottom:16px;">🙏</div>
    <h1 style="color:#1c1917;margin:0 0 12px;">Merci pour votre retour !</h1>
    <p style="color:#57534e;line-height:1.6;">Votre avis a bien été enregistré.</p>
    <p style="color:#a8a29e;font-size:13px;margin-top:24px;">Vous pouvez fermer cette fenêtre.</p>
  </div>
</body>
</html>"""

ERROR_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Erreur</title></head>
<body style="margin:0;padding:40px;background:#f4f4f4;font-family:sans-serif;text-align:center;">
  <div style="max-width:480px;margin:80px auto;background:#fff;border-radius:8px;
              padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
    <div style="font-size:48px;margin-bottom:16px;">❌</div>
    <h1 style="color:#b91c1c;margin:0 0 12px;">Erreur d'authentification</h1>
    <p style="color:#57534e;">{{ error | e }}</p>
    <p style="margin-top:24px;"><a href="/auth" style="color:#b91c1c;">Réessayer →</a></p>
  </div>
</body>
</html>"""

UNSUBSCRIBE_ERROR_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Erreur de désinscription</title></head>
<body style="margin:0;padding:40px;background:#faf8f4;font-family:sans-serif;text-align:center;">
  <div style="max-width:480px;margin:80px auto;background:#fff;border-radius:8px;
              padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <div style="font-size:48px;margin-bottom:16px;">❌</div>
    <h1 style="color:#b91c1c;margin:0 0 12px;">Désinscription impossible</h1>
    <p style="color:#57534e;">{{ error | e }}</p>
    <p style="color:#a8a29e;font-size:13px;margin-top:24px;">
      Si le problème persiste, répondez à l'email de la newsletter pour vous désinscrire manuellement.
    </p>
  </div>
</body>
</html>"""

INTERACTION_ERROR_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Lien invalide</title></head>
<body style="margin:0;padding:40px;background:#faf8f4;font-family:sans-serif;text-align:center;">
  <div style="max-width:400px;margin:80px auto;background:#fff;border-radius:8px;
              padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <div style="font-size:48px;margin-bottom:16px;">❌</div>
    <h1 style="color:#b91c1c;margin:0 0 12px;font-size:18px;">Lien invalide ou expiré</h1>
    <p style="color:#57534e;font-size:14px;">Ce lien n'est plus valide. Retrouvez la newsletter dans votre boîte mail.</p>
  </div>
</body>
</html>"""

REACTION_CONFIRM_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Réaction enregistrée</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:40px;background:#faf8f4;font-family:sans-serif;text-align:center;">
  <div style="max-width:400px;margin:80px auto;background:#fff;border-radius:8px;
              padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <div style="font-size:64px;margin-bottom:16px;">{{ emoji }}</div>
    {% if is_update %}
    <h1 style="color:#1c1917;margin:0 0 12px;font-size:20px;">Avis mis à jour !</h1>
    {% else %}
    <h1 style="color:#1c1917;margin:0 0 12px;font-size:20px;">Merci !</h1>
    {% endif %}
    <p style="color:#a8a29e;font-size:13px;margin-top:8px;">Vous pouvez fermer cette fenêtre.</p>
  </div>
</body>
</html>"""

FEEDBACK_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Votre avis — {{ date_str }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,400&family=Lora:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
  <style>
    :root {
      --rouge:#c9001e; --noir:#1c1917; --creme:#ede8df; --blanc:#faf8f4;
      --gris:#78716c; --bordure:#e5dfd5; --vert:#15803d; --vert-bg:#f0fdf4;
    }
    *, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
    body { background:var(--creme); color:var(--noir); font-family:'Lora',Georgia,serif; min-height:100vh; }

    /* HEADER COMPACT */
    .header {
      background:var(--noir); border-top:4px solid var(--rouge);
      padding:20px 24px 16px;
    }
    .header-inner {
      max-width:640px; margin:0 auto;
      display:flex; align-items:center; justify-content:space-between; gap:16px;
    }
    .header-brand {
      font-family:'Lora',serif; font-size:9px; letter-spacing:3px;
      text-transform:uppercase; color:var(--rouge);
    }
    .header-title {
      font-family:'Playfair Display',serif; font-size:18px;
      font-weight:700; color:var(--blanc); white-space:nowrap;
    }
    .header-date { font-size:11px; color:#a09080; font-style:italic; }

    /* GLOBAL REACTION BAR */
    .reaction-bar {
      background:var(--blanc); border-bottom:1px solid var(--bordure);
    }
    .reaction-bar-inner {
      max-width:640px; margin:0 auto;
      padding:14px 24px;
      display:flex; align-items:center; gap:14px;
    }
    .reaction-bar-emoji { font-size:28px; line-height:1; flex-shrink:0; }
    .reaction-bar-label { font-size:9px; letter-spacing:2px; text-transform:uppercase; color:var(--gris); }
    .reaction-bar-text {
      font-family:'Playfair Display',serif; font-size:15px;
      font-weight:700; color:var(--noir); font-style:italic;
    }
    .reaction-bar-sep { width:1px; height:32px; background:var(--bordure); flex-shrink:0; }

    /* BODY */
    .body { max-width:640px; margin:0 auto; padding:32px 24px 72px; }

    /* SECTION TOGGLE ROW */
    .section-row {
      display:flex; align-items:center; justify-content:space-between;
      padding:16px 20px; background:var(--blanc);
      border-radius:12px; border:1px solid var(--bordure);
      margin-bottom:4px; cursor:pointer; user-select:none;
      transition:box-shadow 0.15s;
    }
    .section-row:hover { box-shadow:0 2px 12px rgba(28,25,23,0.07); }
    .section-row-label {
      font-family:'Playfair Display',serif; font-size:16px;
      font-weight:700; color:var(--noir);
    }
    .section-row-hint { font-size:11px; color:var(--gris); font-style:italic; margin-top:2px; }

    /* TOGGLE SWITCH */
    .toggle { position:relative; width:44px; height:24px; flex-shrink:0; }
    .toggle input { opacity:0; width:0; height:0; position:absolute; }
    .toggle-track {
      position:absolute; inset:0; background:#d1cdc7;
      border-radius:24px; transition:background 0.2s;
    }
    .toggle-thumb {
      position:absolute; top:3px; left:3px;
      width:18px; height:18px; background:#fff;
      border-radius:50%; transition:transform 0.2s; box-shadow:0 1px 3px rgba(0,0,0,0.2);
    }
    .toggle input:checked ~ .toggle-track { background:var(--rouge); }
    .toggle input:checked ~ .toggle-thumb { transform:translateX(20px); }

    /* ARTICLES LIST */
    .articles-list {
      overflow:hidden; max-height:0;
      transition:max-height 0.35s ease, opacity 0.25s ease;
      opacity:0;
    }
    .articles-list.open { max-height:3000px; opacity:1; }

    /* ARTICLE ROW — single line */
    .arow {
      display:flex; align-items:center; gap:16px;
      background:var(--blanc); border:1px solid var(--bordure);
      border-left:3px solid transparent;
      border-radius:10px; padding:14px 18px;
      margin-top:6px; transition:border-left-color 0.2s;
    }
    .arow.reacted-like    { border-left-color:var(--vert); }
    .arow.reacted-meh     { border-left-color:#92400e; }
    .arow.reacted-dislike { border-left-color:var(--rouge); }

    .arow-num {
      font-family:'Lora',serif; font-size:10px; font-weight:500;
      color:var(--rouge); letter-spacing:1px; flex-shrink:0; width:24px;
      text-align:center;
    }
    .arow-title {
      font-family:'Playfair Display',serif; font-size:14px;
      font-weight:700; color:var(--noir); line-height:1.3; flex:1; min-width:0;
    }
    .arow-btns { display:flex; gap:6px; flex-shrink:0; }
    .rbtn {
      border:1.5px solid var(--bordure); border-radius:8px;
      background:var(--creme); width:40px; height:36px;
      cursor:pointer; font-size:16px; line-height:1;
      display:flex; align-items:center; justify-content:center;
      transition:all 0.13s ease; flex-shrink:0;
    }
    .rbtn:hover { border-color:var(--noir); background:var(--blanc); transform:scale(1.1); }
    .rbtn.sel-like    { border-color:var(--vert);   background:var(--vert-bg); }
    .rbtn.sel-meh     { border-color:#92400e; background:#fffbeb; }
    .rbtn.sel-dislike { border-color:var(--rouge);  background:#fff1f2; }

    /* COMMENT */
    .comment-section { margin-top:24px; }
    .comment-label {
      font-family:'Playfair Display',serif; font-size:16px;
      font-weight:700; color:var(--noir); margin-bottom:4px; display:block;
    }
    .comment-hint { font-size:11px; color:var(--gris); font-style:italic; margin-bottom:12px; display:block; }
    textarea {
      width:100%; border:1.5px solid var(--bordure); border-radius:10px;
      padding:14px 16px; font-family:'Lora',serif; font-size:14px;
      color:var(--noir); background:var(--blanc); resize:vertical;
      min-height:90px; line-height:1.7; transition:border-color 0.15s;
    }
    textarea:focus { outline:none; border-color:var(--rouge); }
    textarea::placeholder { color:#c4bfb8; font-style:italic; }

    /* SUBMIT */
    .submit-btn {
      width:100%; background:var(--noir); color:var(--blanc);
      border:none; border-radius:10px; padding:16px 24px; margin-top:20px;
      font-family:'Playfair Display',serif; font-size:17px;
      font-weight:700; cursor:pointer; letter-spacing:-0.2px;
      transition:background 0.2s; position:relative; overflow:hidden;
    }
    .submit-btn::after {
      content:''; position:absolute; left:0; bottom:0;
      width:0; height:3px; background:var(--rouge); transition:width 0.3s ease;
    }
    .submit-btn:hover { background:#2c2621; }
    .submit-btn:hover::after { width:100%; }

    @keyframes rise {
      from { opacity:0; transform:translateY(8px); }
      to   { opacity:1; transform:translateY(0); }
    }
    .body { animation:rise 0.3s ease; }

    @media(max-width:500px){
      .header-inner { flex-direction:column; align-items:flex-start; gap:4px; }
      .arow { flex-wrap:wrap; }
      .arow-title { width:100%; }
      .arow-btns { margin-left:32px; }
    }
  </style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <div>
      <div class="header-brand">&#9679; Daily News &bull; Votre avis</div>
      <div class="header-title">Newsletter du {{ date_str }}</div>
    </div>
  </div>
</div>

{% set gmap = {'like': ['👍', 'Vous avez aimé cette édition'], 'meh': ['😐', 'Cette édition vous a semblé moyenne'], 'dislike': ['👎', 'Cette édition ne vous a pas convaincu']} %}
{% if global_reaction in gmap %}
<div class="reaction-bar">
  <div class="reaction-bar-inner">
    <span class="reaction-bar-emoji">{{ gmap[global_reaction][0] }}</span>
    <div class="reaction-bar-sep"></div>
    <div>
      <div class="reaction-bar-label">Réaction globale</div>
      <div class="reaction-bar-text">{{ gmap[global_reaction][1] }}</div>
    </div>
  </div>
</div>
{% endif %}

<div class="body">
  <form method="POST" action="/feedback">
    <input type="hidden" name="email"  value="{{ email_hash }}">
    <input type="hidden" name="date"   value="{{ date_str }}">
    <input type="hidden" name="token"  value="{{ token }}">
    <input type="hidden" name="global" value="{{ global_reaction }}">

    {% if articles %}
    <div class="section-row" onclick="rowClick()">
      <div>
        <div class="section-row-label">Réagir article par article</div>
        <div class="section-row-hint">Optionnel — noter chaque article individuellement</div>
      </div>
      <label class="toggle" onclick="event.stopPropagation()">
        <input type="checkbox" id="art-toggle" onchange="syncList()">
        <div class="toggle-track"></div>
        <div class="toggle-thumb"></div>
      </label>
    </div>

    <div class="articles-list" id="articles-list">
      {% for art in articles %}
      <div class="arow" id="arow{{ art.rank }}">
        <input type="hidden" id="r{{ art.rank }}" name="reaction_{{ art.rank }}" value="">
        <span class="arow-num">{{ art.rank }}</span>
        <span class="arow-title">{{ art.title }}</span>
        <div class="arow-btns">
          <button type="button" class="rbtn" title="Top" onclick="pick({{ art.rank }},'like',this)">👍</button>
          <button type="button" class="rbtn" title="Moyen" onclick="pick({{ art.rank }},'meh',this)">😐</button>
          <button type="button" class="rbtn" title="Non" onclick="pick({{ art.rank }},'dislike',this)">👎</button>
        </div>
      </div>
      {% endfor %}
    </div>
    {% endif %}

    <div class="comment-section" style="margin-top:20px;">
      <label class="comment-label" for="comment">Un mot à ajouter&nbsp;?</label>
      <span class="comment-hint">Votre retour nous aide à améliorer chaque édition. (optionnel)</span>
      <textarea id="comment" name="comment" placeholder="Dites-nous ce que vous avez pensé…"></textarea>
    </div>

    <button type="submit" class="submit-btn">Envoyer mon avis &rarr;</button>
  </form>
</div>

<script>
  function rowClick() {
    var cb = document.getElementById('art-toggle');
    cb.checked = !cb.checked;
    document.getElementById('articles-list').classList.toggle('open', cb.checked);
  }
  function syncList() {
    var cb = document.getElementById('art-toggle');
    document.getElementById('articles-list').classList.toggle('open', cb.checked);
  }
  function pick(rank, val, btn) {
    btn.parentElement.querySelectorAll('.rbtn').forEach(function(b){ b.className='rbtn'; });
    btn.classList.add('sel-' + val);
    document.getElementById('r' + rank).value = val;
    var row = document.getElementById('arow' + rank);
    row.className = 'arow reacted-' + val;
  }
</script>
</body>
</html>"""

FEEDBACK_CONFIRM_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Merci !</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:40px;background:#faf8f4;font-family:sans-serif;text-align:center;">
  <div style="max-width:400px;margin:80px auto;background:#fff;border-radius:8px;
              padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <div style="font-size:64px;margin-bottom:16px;">🙏</div>
    <h1 style="color:#1c1917;margin:0 0 12px;font-size:22px;">Merci pour votre avis !</h1>
    <p style="color:#57534e;font-size:14px;line-height:1.6;">
      Votre retour nous aide à améliorer la newsletter chaque jour.
    </p>
    <p style="color:#a8a29e;font-size:12px;margin-top:20px;">Vous pouvez fermer cette fenêtre.</p>
  </div>
</body>
</html>"""

STATS_AUTH_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Accès restreint</title></head>
<body style="margin:0;padding:40px;background:#faf8f4;font-family:sans-serif;text-align:center;">
  <div style="max-width:400px;margin:80px auto;background:#fff;border-radius:8px;
              padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <div style="font-size:48px;margin-bottom:16px;">🔒</div>
    <h1 style="color:#1c1917;margin:0 0 12px;font-size:20px;">Accès restreint</h1>
    <p style="color:#57534e;font-size:14px;">Ajoutez <code>?token=VOTRE_TOKEN</code> à l'URL.</p>
  </div>
</body>
</html>"""

STATS_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><title>Stats {{ send_date }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { margin:0; padding:20px; background:#ede8df; font-family:Arial,sans-serif; color:#1c1917; }
    .container { max-width:700px; margin:0 auto; }
    h1 { font-family:Georgia,serif; font-size:24px; margin:0 0 4px; }
    .subtitle { color:#78716c; font-size:13px; margin:0 0 24px; }
    .grid { display:flex; gap:12px; margin-bottom:24px; flex-wrap:wrap; }
    .kpi { flex:1; min-width:120px; background:#fff; border-radius:8px; padding:16px;
           border:1px solid #e5dfd5; text-align:center; }
    .kpi-value { font-size:28px; font-weight:700; color:#c9001e; }
    .kpi-pct { font-size:14px; color:#78716c; }
    .kpi-label { font-size:11px; color:#a09080; text-transform:uppercase; letter-spacing:1px; margin-top:4px; }
    .card { background:#fff; border-radius:8px; border:1px solid #e5dfd5;
            border-left:4px solid #c9001e; padding:16px 20px; margin-bottom:10px; }
    .card-title { font-family:Georgia,serif; font-size:15px; font-weight:700; margin:0 0 10px; }
    .metrics { display:flex; gap:16px; flex-wrap:wrap; font-size:13px; }
    .metric { color:#57534e; }
    .metric strong { color:#1c1917; }
    .score { float:right; font-size:11px; color:#a09080; }
    .no-data { text-align:center; padding:40px; color:#a09080; font-size:14px; }
    @media(max-width:500px){ .grid { flex-direction:column; } }
  </style>
</head>
<body>
<div class="container">
  <h1>📊 Newsletter — {{ send_date }}</h1>
  <p class="subtitle">Métriques d'engagement de l'édition</p>

  <div class="grid">
    <div class="kpi">
      <div class="kpi-value">{{ sent }}</div>
      <div class="kpi-label">Envoyés</div>
    </div>
    <div class="kpi">
      <div class="kpi-value">{{ unique_opens }}</div>
      <div class="kpi-pct">{{ pct_opens }}</div>
      <div class="kpi-label">Ouvertures</div>
    </div>
    <div class="kpi">
      <div class="kpi-value">{{ unique_clickers }}</div>
      <div class="kpi-pct">{{ pct_clicks }}</div>
      <div class="kpi-label">Clics sources</div>
    </div>
    <div class="kpi">
      <div class="kpi-value">{{ unique_reactors }}</div>
      <div class="kpi-pct">{{ pct_reactions }}</div>
      <div class="kpi-label">Feedbacks</div>
    </div>
  </div>

  {% if no_data %}
  <div class="no-data">Aucune donnée pour cette édition.<br>Les interactions apparaîtront ici au fil de la journée.</div>
  {% else %}

  {% if global_likes or global_mehs or global_dislikes %}
  <p style="font-size:11px;color:#a09080;text-transform:uppercase;letter-spacing:1px;margin:0 0 10px;">Réaction globale à l'édition</p>
  <div class="card" style="border-left-color:#1d4ed8;">
    <div class="metrics" style="justify-content:center;gap:32px;">
      <span class="metric" style="font-size:16px;">👍 <strong>{{ global_likes }}</strong></span>
      <span class="metric" style="font-size:16px;">😐 <strong>{{ global_mehs }}</strong></span>
      <span class="metric" style="font-size:16px;">👎 <strong>{{ global_dislikes }}</strong></span>
    </div>
  </div>
  {% endif %}

  {% if per_article %}
  <p style="font-size:11px;color:#a09080;text-transform:uppercase;letter-spacing:1px;margin:16px 0 10px;">Articles — classés par score d'engagement</p>
  {% for art in per_article %}
  <div class="card">
    <div class="card-title">
      #{{ art.rank }} — {{ art.title }}
      <span class="score">Score : {{ art.score }}</span>
    </div>
    <div class="metrics">
      <span class="metric">🔗 <strong>{{ art.clicks }}</strong> clics sources</span>
      <span class="metric">👍 <strong>{{ art.likes }}</strong></span>
      <span class="metric">😐 <strong>{{ art.mehs }}</strong></span>
      <span class="metric">👎 <strong>{{ art.dislikes }}</strong></span>
    </div>
  </div>
  {% endfor %}
  {% endif %}

  {% if comments %}
  <p style="font-size:11px;color:#a09080;text-transform:uppercase;letter-spacing:1px;margin:16px 0 10px;">Commentaires ({{ comments|length }})</p>
  {% for c in comments %}
  <div class="card" style="border-left-color:#78716c;">
    <p style="margin:0;font-size:14px;color:#57534e;line-height:1.6;">{{ c }}</p>
  </div>
  {% endfor %}
  {% endif %}

  {% endif %}
</div>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Veilleur d'envoi
#
# Le planificateur de GitHub Actions s'est réveillé douze heures en retard les
# 27 et 28 août 2026. Ce serveur, lui, tourne en continu : il constate qu'une
# édition manque et relance le workflow.
#
# Éteint tant que WATCHDOG_ENABLED n'est pas posé — un déclencheur d'envoi ne
# doit jamais s'allumer par effet de bord.
# ---------------------------------------------------------------------------

if os.environ.get("WATCHDOG_ENABLED", "").lower() in ("1", "true", "yes"):
    try:
        from send_watchdog import demarrer as _demarrer_veilleur

        _demarrer_veilleur(_cfg("GITHUB_TOKEN"), _cfg("GITHUB_REPO"))
    except Exception:
        # Un veilleur qui ne démarre pas ne doit pas emporter le serveur :
        # /vie-privee et /unsubscribe ne dépendent de rien, et ça doit le rester.
        logging.getLogger(__name__).exception(
            "Veilleur d'envoi : démarrage impossible — le serveur continue sans."
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
