"""
Tests des points d'entrée de sync_recipients.gs.

Ce fichier est une copie de référence — le code qui tourne vit dans l'éditeur
Apps Script. Ces tests ne l'exécutent donc pas : ils tiennent l'invariant qui
rend le montage possible.

L'invariant : la synchronisation ne doit **jamais** dépendre de l'événement de
soumission. Vérifié le 27 août 2026 — un POST direct vers `/formResponse` crée
bien une ligne dans la Sheet, mais ne déclenche pas `onFormSubmit` : aucune
exécution dans le journal Apps Script, et l'adresse n'atteint jamais
`recipients.toml`. Les inscriptions venues de la landing page ne remontent donc
que par le déclencheur horaire, qui appelle `syncRecipients()` sans événement.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GS = ROOT / "scripts" / "sync_recipients.gs"


def _source() -> str:
    return GS.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    """Corps d'une fonction de premier niveau, jusqu'à l'accolade en colonne 0."""
    src = _source()
    start = src.index(f"function {name}(")
    end = src.index("\n}\n", start)
    return src[start:end]


def test_both_entry_points_exist():
    """
    Deux déclencheurs, deux portes : le formulaire Google et l'horloge.
    Retirer l'une des deux laisse une moitié des inscriptions sur le carreau.
    """
    src = _source()

    assert "function onFormSubmit(" in src
    assert "function syncRecipients(" in src


def test_the_form_trigger_only_delegates():
    """
    Tout le travail vit dans syncRecipients() pour que l'horloge puisse le
    refaire. Si du code redescendait dans onFormSubmit, il ne tournerait plus
    que pour les inscriptions faites dans l'interface Google.
    """
    body = _function_body("onFormSubmit")

    assert "syncRecipients()" in body
    assert "assertRepoReachable_" not in body, "logique redescendue dans onFormSubmit"
    assert "collectEmails_" not in body, "logique redescendue dans onFormSubmit"


def test_the_sync_never_reads_the_submission_event():
    """
    C'est l'invariant central. Un accès à `e.values` ou `e.namedValues` ferait
    planter chaque exécution horaire — donc chaque inscription venue de la
    landing page, en silence.
    """
    body = _function_body("syncRecipients")
    # Les callbacks internes utilisent aussi `e` comme paramètre ; on ne
    # cherche que les accès à un objet d'événement de soumission.
    forbidden = re.findall(r"\be\.(values|namedValues|response|source|triggerUid)\b", body)

    assert not forbidden, f"syncRecipients dépend de l'événement : {forbidden}"


def test_the_sync_rereads_the_whole_sheet():
    """
    C'est ce qui rend l'exécution horaire équivalente à l'exécution sur
    soumission : elle ne rattrape pas un delta, elle repart de la Sheet.
    """
    body = _function_body("syncRecipients")

    assert "collectEmails_()" in body


def test_the_header_documents_both_triggers():
    """
    Le fichier doit se coller dans Apps Script avec son mode d'emploi : sans
    le déclencheur horaire, la landing page ne sert à rien.
    """
    header = _source()[:2000]

    assert "syncRecipients" in header
    assert "onFormSubmit" in header
    assert "/formResponse" in header, "la raison du second déclencheur n'est pas expliquée"
