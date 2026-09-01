"""
Tests de cohérence des workflows.

Écrit après un envoi réel parti SANS le bloc transparence : newsletter.yml
avait alors deux étapes d'envoi — « email uniquement » et « email + Instagram »
— et les variables du bloc n'avaient été ajoutées qu'à la seconde. Le
comportement dépendait donc du mode de déclenchement.

Le workflow a depuis été consolidé en un chemin d'envoi unique (2fcfb61), ce
qui supprime la dérive par construction plutôt que par vérification. Ces tests
restent utiles à deux titres : ils échoueraient si le chemin était re-scindé
sans propager la configuration, et ils vérifient que rien n'est oublié dans
l'étape unique.
"""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WORKFLOW = ROOT / ".github" / "workflows" / "newsletter.yml"

# Variables sans lesquelles le rendu ou l'accès aux données change silencieusement
REQUIRED = {
    "SHOW_TRACKING_NOTICE",
    "DASHBOARD_PUBLIC_URL",
    "PRIVACY_URL",
    "AUTH_SERVER_URL",
    "UNSUBSCRIBE_SECRET",
    "DATA_REPO",
    "GIT_TOKEN",
}


def _job() -> dict:
    return next(iter(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"].values()))


def _send_steps() -> list[dict]:
    return [s for s in _job()["steps"] if "main.py --now" in str(s.get("run", ""))]


def _step_named(fragment: str) -> dict | None:
    return next((s for s in _job()["steps"] if fragment.lower() in s["name"].lower()), None)


def test_there_is_at_least_one_send_step():
    """Garde-fou : sans lui, les tests paramétrés ci-dessous passeraient à vide."""
    assert _send_steps()


@pytest.mark.parametrize("variable", sorted(REQUIRED))
def test_every_send_step_carries_the_variable(variable):
    for step in _send_steps():
        assert variable in (step.get("env") or {}), (
            f"« {step['name']} » ne transmet pas {variable}. Si le chemin d'envoi "
            f"a été scindé, la configuration doit être propagée à chaque branche."
        )


def test_the_send_steps_agree_with_each_other():
    """Sans effet tant qu'il n'y a qu'une étape ; mord dès qu'on en rajoute une."""
    envs = [set(s.get("env") or {}) for s in _send_steps()]
    for other in envs[1:]:
        assert not ((envs[0] ^ other) & REQUIRED), "configuration divergente entre les envois"


# ── Ordre des étapes du dépôt de données (#55) ───────────────────────────────

def test_the_subscriber_data_is_fetched_before_sending():
    """Envoyer avant d'avoir récupéré la liste, c'est envoyer à la mauvaise."""
    names = [s["name"] for s in _job()["steps"]]
    fetch = next(i for i, n in enumerate(names) if "Récupérer les données" in n)
    send = next(i for i, n in enumerate(names) if "main.py --now" in str(_job()["steps"][i].get("run", "")))

    assert fetch < send


def test_the_identifier_table_is_pushed_back():
    """Sans renvoi, l'identifiant d'un nouvel abonné meurt avec le runner."""
    assert _step_named("Renvoyer la table") is not None


def test_the_push_runs_even_if_the_send_failed():
    """Un identifiant a pu être créé avant l'échec : il doit quand même remonter."""
    assert _step_named("Renvoyer la table").get("if") == "always()"


def test_the_local_commit_no_longer_touches_the_identifier_table():
    """Elle est gitignorée ici depuis #55 — la commiter échouerait."""
    commit = _step_named("Commit dashboard")

    assert "subscriber_ids" not in str(commit.get("run", ""))


# ---------------------------------------------------------------------------
# Planification
#
# Les 27 et 28 août 2026, le cron "0 5 * * *" s'est déclenché à 16h02 puis
# 17h10. Le planificateur GitHub fonctionne « au mieux » et déprioritise
# l'heure pile. Entre-temps l'envoi avait été relancé à la main, et le run
# tardif a renvoyé l'édition à tout le monde.
# ---------------------------------------------------------------------------


def _crons() -> list[str]:
    on = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))[True]
    return [c["cron"] for c in on["schedule"]]


def test_le_workflow_reste_declenchable_a_la_demande():
    """
    La relance de secours vit hors de GitHub — auth_server/send_watchdog.py,
    sur un hébergement allumé en continu — parce qu'un second cron partagerait
    le retard du premier. Elle passe par workflow_dispatch : le retirer
    couperait le seul recours quand le planificateur décroche, sans rien
    signaler.
    """
    on = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))[True]
    assert "workflow_dispatch" in on


def test_aucun_declenchement_a_lheure_pile():
    for cron in _crons():
        minute = cron.split()[0]
        assert minute not in ("0", "00"), (
            f"{cron!r} tombe à l'heure pile, le créneau le plus disputé du "
            "planificateur GitHub. Décaler de quelques minutes."
        )


def test_le_journal_denvoi_est_renvoye_au_depot():
    """
    Sans commit du journal, la relance de 8h07 repart d'un fichier vide et
    renvoie l'édition — exactement le doublon qu'on cherche à empêcher.

    On regarde l'étape de commit, pas le fichier entier : le nom apparaît
    aussi dans l'étape de rafraîchissement, qui ne prouve rien ici.
    """
    commit = next(
        st for st in _job()["steps"]
        if "commit" in (st.get("name") or "").lower()
    )
    assert "data/sent_editions.csv" in commit["run"]


def test_le_journal_est_relu_sur_main_avant_lenvoi():
    """
    Un run retardé est checkouté sur un SHA ancien : le journal doit être
    rafraîchi depuis main, sinon le garde-fou raisonne sur un fichier périmé.
    """
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "git checkout origin/main -- data/sent_editions.csv" in src
