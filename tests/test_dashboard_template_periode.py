"""
Contrat du gabarit vis-à-vis du filtre de période.

Ces deux tests existent parce que les deux défauts ont été constatés en
ouvrant la page dans un navigateur, pas en la relisant.

1. Une période sans édition faisait lever `runs[runs.length - 1].ok`. La page
   s'affichait entière et vide : coquille présente, cartes muettes, rien qui
   le signale. C'est exactement ce que public_board.py documente pour les
   tableaux expurgés — « un tableau vidé casse la page aussi sûrement qu'une
   clé absente ».

2. `/dashboard` et `/board` partagent ce gabarit, mais /board reçoit un
   payload sans `series`. Un sélecteur de période y serait un contrôle mort.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GABARIT = ROOT / "auth_server" / "dashboard.html"


@pytest.fixture(scope="module")
def source() -> str:
    return GABARIT.read_text(encoding="utf-8")


def test_une_periode_sans_edition_sort_avant_dindexer(source):
    """
    La garde doit précéder la première indexation, sinon elle ne sert à rien.
    """
    garde = source.index("if (!ED.length)")
    premier_acces = source.index("runs[runs.length - 1]")
    assert garde < premier_acces, \
        "la sortie anticipée doit venir avant runs[runs.length - 1]"


def test_une_periode_sans_edition_le_dit_au_lecteur(source):
    """Une page vide sans explication est un bogue, pas un état."""
    assert "Aucune édition sur la période" in source


def test_labsence_de_run_ne_fait_pas_lever(source):
    """
    L'API Actions ne renvoie qu'un nombre limité de runs : une période
    ancienne peut contenir des éditions sans aucun run connu.
    """
    assert "lastRun ? lastRun.ok" in source


def test_le_selecteur_de_periode_exige_les_series(source):
    """
    Sans `series`, il n'y a rien à recalculer : le contrôle doit disparaître
    plutôt que de proposer des périodes qui ne changeraient rien.
    """
    bloc = source[source.index("function renderPeriods"):]
    bloc = bloc[:bloc.index("function renderAll")]
    assert "if (!D.series) return;" in bloc


def test_la_moyenne_de_reference_annonce_son_vrai_nombre(source):
    """
    Sur une période courte, « moyenne des 30 dernières » est un chiffre juste
    sous une étiquette fausse — pire qu'une étiquette absente.
    """
    assert "const nRef = last30.length;" in source
    assert not re.search(r'"Moyenne des 30 dernières', source)


# ---------------------------------------------------------------------------
# Carte « fiabilité de l'envoi »
#
# Elle ne montrait que réussite ou échec. Les 27, 28, 30 et 31 août, le
# planificateur GitHub s'est réveillé avec cinq à douze heures de retard : des
# envois verts, donc « réussis », mais partis le soir. La dérive était
# invisible ici alors que l'heure figurait déjà dans le payload.
# ---------------------------------------------------------------------------


def test_la_carte_fiabilite_montre_l_heure_reelle(source):
    """
    L'heure réelle ne dit rien sans repère : « parti à 17 h 10 » n'est une
    anomalie que rapporté à l'horaire prévu. Le repère doit donc être rendu,
    pas seulement déclaré.
    """
    assert 'id="runs-detail"' in source
    assert '<u style="left:\' + ((HEURE_PREVUE / 24) * 100)' in source, \
        "le repère de l'heure prévue doit être positionné dans chaque ligne"


def test_le_veilleur_et_une_relance_manuelle_ne_sont_pas_distingues(source):
    """
    L'API ne renvoie que `schedule` et `workflow_dispatch` : une relance du
    veilleur et une relance à la main arrivent identiques. Le dire est plus
    honnête que d'inventer une distinction.
    """
    assert "ne se distinguent pas ici" in source


def test_une_periode_sans_run_ne_divise_pas_par_zero(source):
    """Un filtre de période peut vider `runs` : le taux vaudrait NaN %."""
    assert "runs.length\n    ? Math.round" in source or "runs.length ? Math.round" in source


# ---------------------------------------------------------------------------
# Camembert des thèmes
# ---------------------------------------------------------------------------


def test_les_themes_sont_rendus_en_anneau(source):
    assert 'class="donut" id="topics"' in source


def test_chaque_part_porte_son_compte_et_son_pourcentage(source):
    """
    À neuf parts, l'œil ne compare pas 6,6 % et 7,2 %. La forme donne
    l'ensemble, les chiffres donnent la comparaison — retirer les seconds
    rendrait le graphe joli et muet.
    """
    assert 'class=\\"pc\\"' in source and 'class=\\"ct\\"' in source


def test_la_couleur_distingue_les_trois_familles(source):
    """
    Configuré / hors configuration / non classé est l'information que porte
    ce graphe. Deux parts d'une même famille se distinguent par l'opacité,
    pas par la teinte : la famille reste lisible.
    """
    assert 'const TON = { data: "var(--data)", accent: "var(--accent)", muted: "var(--ink-3)" };' in source
    assert '"stroke-opacity"' in source


# ---------------------------------------------------------------------------
# Infobulles et seuils relatifs
# ---------------------------------------------------------------------------


def test_linfobulle_dassiduite_situe_le_lecteur_sans_lidentifier(source):
    """
    Le lecteur est désigné par son rang. Cette page est protégée par un jeton,
    mais l'assiduité est aussi ce qui part sur /board.
    """
    assert "'<div class=\"tip-d\">lecteur ' + (e.i + 1)" in source
    assert "% de la période" in source


def test_linfobulle_dune_edition_donne_lheure_de_depart(source):
    """
    L'édition la moins ouverte est celle partie le soir. Le lien existait dans
    les données et n'était affiché nulle part.
    """
    assert "const departs = {};" in source
    assert '" · partie à " + r' in source


def test_les_seuils_dassiduite_sont_proportionnels(source):
    """
    Avec un seuil figé à 80 éditions, une période de 7 jours affichait
    « 0 lecteurs ouvrent quasiment chaque édition (80 sur 7 ou plus) » et
    comptait les 25 lecteurs actifs comme absents. Chiffre juste, phrase
    fausse — cela trompe plus qu'un chiffre absent.
    """
    assert "Math.ceil(nEd * 0.75)" in source
    assert "Math.ceil(nEd * 0.2)" in source
    assert "v >= 80" not in source, "un seuil absolu ne survit pas au filtre de période"
