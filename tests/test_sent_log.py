"""
Tests du journal des envois.

Écrit après un doublon réel : le 28 août 2026, le run planifié s'est réveillé
douze heures en retard et a renvoyé l'édition déjà partie le matin par
déclenchement manuel. Vingt-huit personnes l'ont reçue deux fois.

Le retard du planificateur GitHub ne se corrige pas de l'intérieur. Ce journal
ne le corrige pas non plus : il rend la relance inoffensive quand l'édition est
déjà partie, ce qui est la seule garantie qu'on puisse tenir soi-même.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.sent_log import already_sent, record_send  # noqa: E402


@pytest.fixture
def journal(tmp_path) -> Path:
    return tmp_path / "sent_editions.csv"


def test_une_edition_jamais_envoyee_nest_pas_marquee(journal):
    assert already_sent("2026-08-29", path=journal) is False


def test_une_edition_enregistree_est_reconnue(journal):
    record_send("2026-08-29", 29, path=journal)
    assert already_sent("2026-08-29", path=journal) is True


def test_une_autre_date_reste_envoyable(journal):
    record_send("2026-08-29", 29, path=journal)
    assert already_sent("2026-08-30", path=journal) is False


def test_enregistrer_deux_fois_ne_duplique_pas_la_ligne(journal):
    record_send("2026-08-29", 29, path=journal)
    record_send("2026-08-29", 29, path=journal)
    lignes = [l for l in journal.read_text(encoding="utf-8").splitlines() if "2026-08-29" in l]
    assert len(lignes) == 1


def test_le_journal_ne_porte_aucune_adresse(journal):
    """
    Le fichier est suivi par git et deviendra public avec le dépôt. Il ne doit
    contenir que des dates et des comptages — jamais qui a reçu quoi.
    """
    record_send("2026-08-29", 29, path=journal)
    assert "@" not in journal.read_text(encoding="utf-8")


def test_un_journal_illisible_laisse_partir_lenvoi(journal, caplog):
    """
    Choix délibéré : en cas de fichier corrompu, on renvoie False, donc l'envoi
    a lieu. Un doublon est désagréable ; une édition muette l'est davantage, et
    surtout elle ne se rattrape pas. L'erreur est journalisée en ERROR.
    """
    journal.write_text("\x00\x00 pas un csv", encoding="utf-8")
    assert already_sent("2026-08-29", path=journal) is False


def test_le_dossier_parent_est_cree_au_besoin(tmp_path):
    cible = tmp_path / "data" / "sent_editions.csv"
    record_send("2026-08-29", 29, path=cible)
    assert cible.exists()
