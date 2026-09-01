"""
Gmail token re-authentication notifier.
=========================================
When the Gmail OAuth token is expired/revoked (invalid_grant), this module
sends a notification email via SMTP App Password so the user can renew access
with a single click — no manual file editing required.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import config

logger = logging.getLogger(__name__)


def send_reauth_email() -> bool:
    """
    Send a re-authentication email via SMTP App Password.

    The email contains a button pointing to the auth server (/auth route),
    which starts the Google OAuth flow and auto-updates the GitHub Secret on completion.

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    if not config.GMAIL_APP_PASSWORD:
        logger.error(
            "GMAIL_APP_PASSWORD is not configured. "
            "Cannot send re-auth notification. "
            "Set it in your .env or GitHub Secrets."
        )
        return False

    if not config.AUTH_SERVER_URL:
        logger.error(
            "AUTH_SERVER_URL is not configured. "
            "Deploy the auth_server/ app and set AUTH_SERVER_URL."
        )
        return False

    auth_url = f"{config.AUTH_SERVER_URL.rstrip('/')}/auth"
    recipient = config.GMAIL_FROM  # send to the sender (= the account owner)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🔑 Action requise — Renouveler l'accès Gmail de la newsletter"
    msg["From"] = f"{config.FROM_NAME} <{config.GMAIL_FROM}>"
    msg["To"] = recipient

    plain = (
        f"Le token Gmail de votre agent newsletter a expiré.\n\n"
        f"Cliquez sur ce lien pour renouveler l'accès (30 secondes) :\n{auth_url}\n\n"
        f"Après authentification, le token sera mis à jour automatiquement dans GitHub Actions."
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:40px 20px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

        <!-- Header -->
        <tr>
          <td style="background:#1c1917;padding:28px 32px;border-bottom:3px solid #b91c1c;">
            <p style="margin:0;color:#f5f5f4;font-size:13px;letter-spacing:1px;text-transform:uppercase;">
              Daily News Agent
            </p>
            <h1 style="margin:8px 0 0;color:#ffffff;font-size:22px;font-weight:700;">
              🔑 Token Gmail expiré
            </h1>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 16px;color:#292524;font-size:16px;line-height:1.6;">
              L'agent newsletter <strong>n'a pas pu envoyer la newsletter d'aujourd'hui</strong>
              car le token Gmail a expiré ou été révoqué.
            </p>
            <p style="margin:0 0 28px;color:#57534e;font-size:15px;line-height:1.6;">
              Cliquez sur le bouton ci-dessous pour renouveler l'accès en 30 secondes.
              Le token sera mis à jour <strong>automatiquement</strong> dans GitHub Actions.
            </p>

            <!-- CTA Button -->
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="border-radius:6px;background:#b91c1c;">
                  <a href="{auth_url}"
                     style="display:inline-block;padding:14px 32px;color:#ffffff;
                            font-size:16px;font-weight:600;text-decoration:none;
                            border-radius:6px;letter-spacing:0.3px;">
                    Renouveler l'accès Gmail →
                  </a>
                </td>
              </tr>
            </table>

            <p style="margin:28px 0 0;color:#a8a29e;font-size:13px;line-height:1.5;">
              En cliquant, vous serez redirigé vers Google pour autoriser l'accès.<br>
              Aucune intervention manuelle supplémentaire n'est nécessaire.<br><br>
              Si le bouton ne fonctionne pas, copiez ce lien :<br>
              <a href="{auth_url}" style="color:#b91c1c;word-break:break-all;">{auth_url}</a>
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f5f5f4;padding:16px 32px;border-top:1px solid #e7e5e4;">
            <p style="margin:0;color:#a8a29e;font-size:12px;">
              Daily News Agent — notification automatique
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(config.GMAIL_FROM, config.GMAIL_APP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Re-auth notification sent to {recipient}")
        return True
    except Exception as e:
        logger.error(f"Failed to send re-auth notification: {e}")
        return False
