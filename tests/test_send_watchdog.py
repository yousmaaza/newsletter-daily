"""
Tests du veilleur d'envoi.

Le planificateur de GitHub Actions fonctionne « au mieux » : les 27 et 28 août
2026, le déclenchement quotidien s'est réveillé onze puis douze heures en
retard. Un second cron n'y changerait rien — il dépend du même planificateur.

La vérification vit donc dans auth_server, sur Railway, qui tourne en continu
et ne dépend pas de GitHub pour savoir quelle heure il est. Il constate qu'une
édition manque et relance le workflow.

C'est le journal d'envoi (tools/sent_log.py) qui rend ça sûr : une relance à
tort ne renvoie rien.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auth_server.send_watchdog import SendWatchdog  # noqa: E402


def at(h: int, m: int = 0, day: int = 29) -> datetime:
    return datetime(2026, 8, day, h, m, tzinfo=timezone.utc)


class Faux:
    """Remplace le réseau : on décide ce que GitHub répond, on compte les relances."""

    def __init__(self, dates_envoyees=(), lisible=True):
        self.dates = set(dates_envoyees)
        self.lisible = lisible
        self.relances = []

    def est_envoyee(self, date_str):
        if not self.lisible:
            raise OSError("GitHub injoignable")
        return date_str in self.dates

    def relancer(self, date_str):
        self.relances.append(date_str)
        return True

    def compter(self, date_str):
        return 0


def veilleur(faux, **kw):
    return SendWatchdog(est_envoyee=faux.est_envoyee, relancer=faux.relancer,
                        compter_tentatives=faux.compter, **kw)


def test_avant_lheure_limite_on_ne_relance_pas():
    """Le pipeline a le droit d'être en retard : c'est la normalité, pas la panne."""
    f = Faux()
    veilleur(f).tick(at(7, 0))
    assert f.relances == []


def test_apres_lheure_limite_une_edition_manquante_est_relancee():
    f = Faux()
    veilleur(f).tick(at(8, 45))
    assert f.relances == ["2026-08-29"]


def test_une_edition_deja_partie_nest_pas_relancee():
    f = Faux(dates_envoyees=["2026-08-29"])
    veilleur(f).tick(at(8, 45))
    assert f.relances == []


def test_un_envoi_survenu_entre_deux_ticks_arrete_les_relances():
    f = Faux()
    w = veilleur(f)
    w.tick(at(8, 45))
    f.dates.add("2026-08-29")
    w.tick(at(9, 0))
    assert f.relances == ["2026-08-29"]


def test_un_etat_illisible_ne_declenche_rien():
    """
    Ne pas savoir n'est pas savoir que non. Relancer à l'aveugle sur une panne
    d'API ajouterait une avarie à une autre.
    """
    f = Faux(lisible=False)
    veilleur(f).tick(at(8, 45))
    assert f.relances == []


def test_lheure_limite_est_configurable():
    f = Faux()
    veilleur(f, heure_limite="10:00").tick(at(9, 30))
    assert f.relances == []


# ---------------------------------------------------------------------------
# Deux défauts constatés le 31 août 2026
#
# 1. Le compteur vivait en mémoire. Chaque redéploiement de Railway — et il y
#    en avait jusqu'à trente-six par jour — le remettait à zéro : « trois
#    tentatives » n'était donc une limite que jusqu'au prochain redémarrage.
#
# 2. declencher_envoi() attribuait tout 403 à une permission manquante. La
#    vraie cause était qu'il y avait deux jetons différents, et que celui posé
#    sur Railway n'était pas celui dont les permissions avaient été corrigées.
#    Le message a fait chercher au mauvais endroit pendant deux jours.
# ---------------------------------------------------------------------------


class FauxCompte:
    """Le compteur vient de l'extérieur : le veilleur ne retient plus rien."""

    def __init__(self, runs_du_jour):
        self.runs = runs_du_jour
        self.relances = []

    def est_envoyee(self, d):
        return False

    def compter(self, d):
        return self.runs

    def relancer(self, d):
        self.relances.append(d)
        return True


def test_le_plafond_se_lit_a_l_exterieur_et_survit_a_un_redemarrage():
    """
    Trois runs ont déjà eu lieu aujourd'hui : un veilleur qui vient de
    redémarrer doit le savoir sans l'avoir vécu.
    """
    f = FauxCompte(runs_du_jour=3)
    w = SendWatchdog(est_envoyee=f.est_envoyee, relancer=f.relancer,
                     compter_tentatives=f.compter)
    assert w.tick(at(8, 45)) == "plafond atteint"
    assert f.relances == []


def test_un_veilleur_neuf_relance_si_aucun_run_na_eu_lieu():
    f = FauxCompte(runs_du_jour=0)
    w = SendWatchdog(est_envoyee=f.est_envoyee, relancer=f.relancer,
                     compter_tentatives=f.compter)
    assert w.tick(at(8, 45)) == "relance déclenchée"
    assert f.relances == ["2026-08-29"]


def test_un_comptage_impossible_ne_relance_pas():
    """Dans le doute sur le nombre de tentatives déjà faites, on s'abstient."""
    def compter_casse(d):
        raise OSError("API injoignable")
    f = FauxCompte(runs_du_jour=0)
    w = SendWatchdog(est_envoyee=f.est_envoyee, relancer=f.relancer,
                     compter_tentatives=compter_casse)
    assert w.tick(at(8, 45)) == "état inconnu"
    assert f.relances == []


def test_le_message_de_403_ne_devine_pas_la_cause(caplog):
    """
    Il doit rapporter ce que GitHub a répondu, et citer les deux causes
    possibles sans en choisir une. Affirmer « il manque la permission » alors
    que le vrai problème était un autre jeton a coûté deux jours.
    """
    import auth_server.send_watchdog as w

    class Reponse:
        status_code = 403
        text = '{"message": "Resource not accessible by personal access token"}'
        def json(self):
            return {"message": "Resource not accessible by personal access token"}

    with caplog.at_level("ERROR"):
        w._journaliser_refus(Reponse())

    msg = caplog.text
    assert "Resource not accessible by personal access token" in msg, \
        "le message réel de GitHub doit apparaître"
    assert "jeton" in msg.lower() and "permission" in msg.lower(), \
        "les deux causes possibles doivent être citées"


# ---------------------------------------------------------------------------
# Course entre le cron et le veilleur
#
# Le journal n'est écrit qu'après l'envoi. Si un run est en cours de
# génération quand le veilleur se réveille, l'édition n'y est pas encore : le
# veilleur en déclencherait un second, et les deux enverraient.
#
# La fenêtre était étroite avec une échéance à 08:30 pour un cron à 06:07.
# Elle s'élargit dès qu'on rapproche les deux.
# ---------------------------------------------------------------------------


class FauxEnCours:
    def __init__(self, en_cours):
        self.en_cours = en_cours
        self.relances = []

    def est_envoyee(self, d):
        return False           # le journal n'est écrit qu'après l'envoi

    def compter(self, d):
        return 0

    def course(self, d):
        return self.en_cours

    def relancer(self, d):
        self.relances.append(d)
        return True


def veilleur_course(f):
    return SendWatchdog(est_envoyee=f.est_envoyee, relancer=f.relancer,
                        compter_tentatives=f.compter, envoi_en_cours=f.course)


def test_un_envoi_en_cours_empeche_une_seconde_relance():
    f = FauxEnCours(en_cours=True)
    assert veilleur_course(f).tick(at(8, 45)) == "envoi en cours"
    assert f.relances == []


def test_sans_envoi_en_cours_la_relance_a_lieu():
    f = FauxEnCours(en_cours=False)
    assert veilleur_course(f).tick(at(8, 45)) == "relance déclenchée"
    assert f.relances == ["2026-08-29"]
