"""
Daily News Newsletter Agent
============================
Uses Claude AI + Brave Search + Gmail to generate and send a daily newsletter.

Usage:
  # Newsletter uniquement :
  python main.py --now

  # Aperçu local, sans aucun envoi :
  python main.py --preview [DATE]

  # Réexpédier une édition à une seule adresse :
  python main.py --send-test moi@example.com [DATE]

  # Démarrer le scheduler (envoie chaque jour à l'heure configurée) :
  python main.py
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from agent import run_agent
from tools.sent_log import already_sent
from config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def preview_newsletter(target_date: str, with_notice: bool = False) -> None:
    """
    Rend la newsletter d'une date dans output/preview/{date}.html.
    Aucun email n'est envoyé, aucune URL de mesure n'est générée.
    """
    from tools.newsletter_renderer import write_preview

    try:
        out_path = write_preview(target_date, with_notice=with_notice)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        sys.exit(1)

    logger.info(f"✅ Aperçu écrit : {out_path}")
    logger.info(f"   Ouvre-le avec :  open {out_path}")


def send_test_newsletter(
    test_email: str,
    target_date: str,
    with_notice: bool = False,
    data_file: str | None = None,
) -> None:
    """
    Réexpédie l'édition sauvegardée d'une date à UNE SEULE adresse.
    La liste d'abonnés n'est jamais utilisée.
    """
    from tools.gmail_tool import send_newsletter_email
    from tools.newsletter_renderer import (
        load_newsletter_data,
        render_for_recipient,
        require_transparency_notice,
    )

    try:
        data = load_newsletter_data(
            target_date, data_file=Path(data_file) if data_file else None)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        sys.exit(1)

    # Le bloc est construit une fois, avec les URL réelles : le bouton reçu
    # dans l'email pointe vers le serveur déployé et fonctionne vraiment.
    notice = None
    if with_notice:
        try:
            notice = require_transparency_notice(
                test_email,
                target_date,
                auth_server_url=config.AUTH_SERVER_URL,
                secret=config.UNSUBSCRIBE_SECRET,
                dashboard_url=config.DASHBOARD_PUBLIC_URL,
                privacy_url=config.PRIVACY_URL,
                subscriber_count=len(config.GMAIL_TO),
            )
        except ValueError as e:
            logger.error(f"❌ {e}")
            sys.exit(1)
        logger.warning(
            "Le bloc transparence est inclus — le lien de refus est RÉEL. "
            "Le suivre te retirera de la mesure jusqu'à ce que tu te retires "
            "de config/tracking_optout.toml."
        )

    def _render(recipient_email: str) -> str:
        return render_for_recipient(
            data,
            recipient_email,
            target_date,
            auth_server_url=config.AUTH_SERVER_URL,
            secret=config.UNSUBSCRIBE_SECRET,
            feedback_form_url=config.FEEDBACK_FORM_URL,
            transparency_notice=notice,
        )

    subject = f"[TEST] {data.get('subject') or data.get('newsletter_title') or target_date}"
    logger.info(f"Envoi de test de l'édition du {target_date} à {test_email}...")

    try:
        result = send_newsletter_email(
            subject=subject,
            html_content="",
            get_html_for_recipient=_render,
            recipients_override=[test_email],
        )
    except FileNotFoundError as e:
        # OAuth non initialisé en local : bascule sur SMTP + mot de passe d'application.
        # Acceptable pour un envoi de test ; l'envoi réel reste sur OAuth.
        logger.warning(f"OAuth Gmail indisponible ({str(e).splitlines()[0]})")
        logger.info("Bascule sur SMTP + GMAIL_APP_PASSWORD pour cet envoi de test...")
        from tools.gmail_tool import send_test_via_smtp

        try:
            result = send_test_via_smtp(subject, test_email, _render(test_email))
        except ValueError as smtp_error:
            logger.error(f"❌ {smtp_error}")
            sys.exit(1)

    if result.get("success"):
        logger.info(f"✅ Envoi de test réussi — {result['sent']}/{result['total']} destinataire(s)")
    else:
        logger.error(f"❌ Envoi de test échoué : {result}")
        sys.exit(1)


def start_scheduler() -> None:
    """Start the APScheduler to run the agent every day at the configured time."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    hour, minute = config.SCHEDULE_TIME.split(":")
    scheduler = BlockingScheduler(timezone=config.TIMEZONE)
    scheduler.add_job(
        run_agent,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=config.TIMEZONE),
        id="daily_newsletter",
        name="Daily News Newsletter",
        replace_existing=True,
    )
    logger.info(
        f"Scheduler started. Newsletter will be sent every day at "
        f"{config.SCHEDULE_TIME} ({config.TIMEZONE})"
    )
    logger.info("Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily News Newsletter Agent")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Avec --now : renvoie l'édition même si elle est déjà partie aujourd'hui.",
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Envoie la newsletter immédiatement",
    )
    parser.add_argument(
        "--preview",
        nargs="?",
        const="today",
        metavar="DATE",
        help=(
            "Écrit la newsletter dans output/preview/DATE.html sans rien envoyer. "
            "Aucun pixel ni lien de mesure n'est généré. "
            "Format DATE : YYYY-MM-DD. Sans argument = date du jour."
        ),
    )
    parser.add_argument(
        "--with-notice",
        action="store_true",
        help=(
            "Inclut le bloc transparence. Avec --preview : liens factices. "
            "Avec --send-test : liens RÉELS, cliquables — c'est le seul moyen de "
            "tester la chaîne complète de refus de mesure."
        ),
    )
    parser.add_argument(
        "--data-file",
        metavar="CHEMIN",
        help=(
            "Avec --send-test : compose depuis ce fichier au lieu de chercher "
            "output/newsletter/DATE/data.json. Permet de valider un rendu sans "
            "lancer la génération, donc sans consommer de crédits Anthropic."
        ),
    )
    parser.add_argument(
        "--send-test",
        nargs="+",
        metavar=("EMAIL", "DATE"),
        help=(
            "Envoie la newsletter à cette seule adresse, jamais à la liste d'abonnés. "
            "Avec --now : lance le pipeline complet et n'envoie qu'à EMAIL. "
            "Sinon : réexpédie l'édition sauvegardée de DATE (défaut : date du jour)."
        ),
    )
    args = parser.parse_args()

    today = date.today().strftime("%Y-%m-%d")

    # --preview : rendu local, aucun envoi, aucun réseau
    if args.preview is not None:
        target = today if args.preview == "today" else args.preview
        preview_newsletter(target, with_notice=args.with_notice)
        sys.exit(0)

    # --send-test sans --now : réexpédition ciblée d'une édition sauvegardée
    if args.send_test and not args.now:
        test_email = args.send_test[0]
        target = args.send_test[1] if len(args.send_test) > 1 else today
        send_test_newsletter(test_email, target, with_notice=args.with_notice,
                             data_file=args.data_file)
        sys.exit(0)

    # --now : envoi de l'édition du jour
    if args.now:
        override = [args.send_test[0]] if args.send_test else None

        # Le planificateur GitHub se réveille parfois avec des heures de retard,
        # après qu'on a relancé l'envoi à la main. Sans ce garde-fou, le run
        # tardif renvoie l'édition à tout le monde — c'est arrivé le 28 août
        # 2026. Un envoi de test n'est pas concerné : il n'inscrit rien.
        #
        # Placé AVANT config.validate() : une édition déjà partie n'a aucune
        # raison d'exiger une configuration complète pour ne rien faire.
        if not override and already_sent(today) and not args.force:
            logger.warning(
                f"Édition du {today} déjà envoyée — rien à faire. "
                "Relancer malgré tout : --now --force."
            )
            sys.exit(0)

        try:
            config.validate()
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)
        if override:
            logger.warning(f"MODE TEST — la newsletter ne partira qu'à {override[0]}")

        run_agent(recipients_override=override)
        sys.exit(0)

    # Par défaut : scheduler
    start_scheduler()
