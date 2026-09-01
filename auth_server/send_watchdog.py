"""
Veilleur d'envoi — vérifie qu'une édition est bien partie, et relance sinon.

Le planificateur de GitHub Actions fonctionne « au mieux ». Les 27 et 28 août
2026, le déclenchement quotidien s'est réveillé onze puis douze heures plus
tard. Ajouter un second cron ne protégerait de rien : il dépend du même
planificateur, et serait déprioritisé de la même façon.

Ce module vit dans auth_server, hébergé ailleurs et allumé en continu. Il ne
demande pas à GitHub quelle heure il est : il le sait, constate qu'une édition
manque passé une certaine heure, et déclenche le workflow.

Ce qui rend la manœuvre sûre, c'est le journal d'envoi côté pipeline
(tools/sent_log.py) : une relance déclenchée à tort ne renvoie rien. Sans ce
garde-fou, ce fichier serait une machine à doublons.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

JOURNAL = "data/sent_editions.csv"
WORKFLOW = "newsletter.yml"


class SendWatchdog:
    """
    Décide s'il faut relancer l'envoi du jour.

    Les accès réseau sont injectés : la décision se teste sans GitHub.
    """

    def __init__(self, est_envoyee, relancer, compter_tentatives,
                 envoi_en_cours=None, heure_limite: str = "08:30",
                 max_tentatives: int = 3):
        self._est_envoyee = est_envoyee
        self._relancer = relancer
        self._compter = compter_tentatives
        self._en_cours = envoi_en_cours or (lambda d: False)
        h, m = heure_limite.split(":")
        self._limite = (int(h), int(m))
        self._max = max_tentatives

    def tick(self, now: datetime | None = None) -> str:
        """
        Ne conserve rien d'un appel à l'autre.

        Le compteur de tentatives vivait en mémoire, et Railway redéploie à
        chaque commit — jusqu'à trente-six fois par jour, chaque ouverture de
        la newsletter en produisant un. « Trois tentatives » n'était donc une
        limite que jusqu'au prochain redémarrage. Il se lit désormais chez
        GitHub, qui est le seul à savoir combien de runs ont déjà eu lieu.
        """
        now = now or datetime.now(timezone.utc)
        jour = now.strftime("%Y-%m-%d")

        if (now.hour, now.minute) < self._limite:
            return "trop tôt"

        try:
            if self._est_envoyee(jour):
                return "déjà envoyée"
            # Le journal n'est écrit qu'APRÈS l'envoi : un run en cours de
            # génération laisse l'édition absente du journal. Sans cette
            # vérification, le veilleur en lancerait un second et les deux
            # enverraient — d'autant plus probable que l'échéance est proche
            # de l'heure du cron.
            if self._en_cours(jour):
                return "envoi en cours"
            tentatives = self._compter(jour)
        except Exception as e:
            # Ne pas savoir n'est pas savoir que non : relancer à l'aveugle sur
            # une panne d'API ajouterait une avarie à une autre.
            logger.error(f"Veilleur : état illisible ({e}) — aucune relance.")
            return "état inconnu"

        if tentatives >= self._max:
            return "plafond atteint"

        logger.warning(
            f"Veilleur : aucune édition pour le {jour} passé "
            f"{self._limite[0]:02d}:{self._limite[1]:02d} UTC — relance "
            f"({tentatives + 1}/{self._max})."
        )
        self._relancer(jour)
        return "relance déclenchée"


# ---------------------------------------------------------------------------
# Accès réseau — volontairement hors de la classe, pour qu'elle reste testable
# ---------------------------------------------------------------------------

def _entetes(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def edition_envoyee(date_str: str, token: str, repo: str) -> bool:
    """Lit le journal d'envoi sur GitHub. Lève si l'API ne répond pas."""
    r = requests.get(
        f"https://api.github.com/repos/{repo}/contents/{JOURNAL}",
        headers={**_entetes(token), "Accept": "application/vnd.github.raw"},
        timeout=20,
    )
    if r.status_code == 404:
        return False                      # journal pas encore créé
    r.raise_for_status()
    return any(l.split(",")[0].strip() == date_str for l in r.text.splitlines())


def _journaliser_refus(reponse) -> None:
    """
    Rapporte ce que GitHub a répondu, sans choisir la cause.

    La version précédente affirmait « le PAT a besoin d'Actions: read and
    write ». C'était plausible et c'était faux : deux jetons coexistaient, et
    celui posé sur Railway n'était pas celui dont on corrigeait les
    permissions. Le message a fait chercher au mauvais endroit pendant deux
    jours. Un diagnostic supposé coûte plus cher qu'une absence de diagnostic.
    """
    try:
        detail = reponse.json().get("message", "")
    except Exception:
        detail = (getattr(reponse, "text", "") or "")[:200]
    logger.error(
        f"Veilleur : relance refusée ({reponse.status_code}). GitHub répond : "
        f"« {detail} ». Deux causes possibles — le jeton utilisé ici n'a pas la "
        "permission « Actions: read and write », OU ce n'est pas le jeton qu'on "
        "croit. Pour trancher sans rien envoyer, appeler ce même endpoint sur "
        "un workflow inexistant : 404 signifie que la permission est là."
    )


def declencher_envoi(date_str: str, token: str, repo: str) -> bool:
    """Déclenche le workflow. Demande « Actions: read and write » sur le PAT."""
    r = requests.post(
        f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
        headers=_entetes(token), json={"ref": "main"}, timeout=20,
    )
    if r.status_code in (401, 403, 404):
        _journaliser_refus(r)
        return False
    r.raise_for_status()
    logger.info(f"Veilleur : workflow relancé pour le {date_str}.")
    return True


def envoi_en_cours(date_str: str, token: str, repo: str) -> bool:
    """Dit si un run du workflow est en file d'attente ou en cours d'exécution."""
    for statut in ("in_progress", "queued"):
        r = requests.get(
            f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/runs",
            headers=_entetes(token),
            params={"status": statut, "per_page": 1}, timeout=20,
        )
        r.raise_for_status()
        if int(r.json().get("total_count", 0)) > 0:
            return True
    return False


def tentatives_du_jour(date_str: str, token: str, repo: str) -> int:
    """
    Compte les runs du workflow lancés aujourd'hui.

    Le plafond se lit chez GitHub plutôt qu'en mémoire : c'est ce qui le rend
    insensible aux redémarrages. Lève si l'API ne répond pas — l'appelant
    traite l'ignorance comme un refus de relancer.
    """
    r = requests.get(
        f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/runs",
        headers=_entetes(token), params={"created": f">={date_str}", "per_page": 1},
        timeout=20,
    )
    r.raise_for_status()
    return int(r.json().get("total_count", 0))


def demarrer(token: str, repo: str, heure_limite: str | None = None,
             minutes: int = 15) -> SendWatchdog:
    """
    Lance le veilleur dans un fil démon.

    Pas d'ordonnanceur tiers : Railway n'installe que
    auth_server/requirements.txt, et une boucle qui se réveille toutes les
    quinze minutes ne justifie pas d'y ajouter une dépendance.

    Le fil est démon : il n'empêche jamais le serveur de s'arrêter. Et il
    encaisse ses propres erreurs — un veilleur qui tombe ne doit pas emporter
    les pages de désinscription et de vie privée avec lui.
    """
    w = SendWatchdog(
        est_envoyee=lambda d: edition_envoyee(d, token, repo),
        relancer=lambda d: declencher_envoi(d, token, repo),
        compter_tentatives=lambda d: tentatives_du_jour(d, token, repo),
        envoi_en_cours=lambda d: envoi_en_cours(d, token, repo),
        heure_limite=heure_limite or os.environ.get("WATCHDOG_DEADLINE", "08:30"),
    )

    def boucle():
        while True:
            try:
                w.tick()
            except Exception:
                logger.exception("Veilleur : tick en échec — on réessaiera.")
            time.sleep(minutes * 60)

    threading.Thread(target=boucle, name="send-watchdog", daemon=True).start()
    logger.info(
        f"Veilleur d'envoi actif — vérification toutes les {minutes} min, "
        f"relance passé {w._limite[0]:02d}:{w._limite[1]:02d} UTC."
    )
    return w
