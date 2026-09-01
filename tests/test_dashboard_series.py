"""
Tests des séries datées du tableau de bord.

Le constructeur agrégeait tout sur la période complète : `by_rank` arrivait
comme un total unique, `loyalty` comme une liste de comptes. Impossible de
redécouper — donc impossible de proposer « 7 jours / 1 mois / 3 mois ».

Les sources brutes portaient pourtant toutes une date. C'est l'agrégation qui
l'écrasait.

Ces séries permettent au navigateur de recalculer chaque mesure sur la période
choisie. Deux invariants comptent :

  1. agréger la série sur TOUTE la période doit redonner exactement le total
     déjà publié — sans quoi les deux vues se contrediraient ;
  2. aucune série ne doit porter d'identifiant de lecteur. La fidélité devient
     bien plus parlante une fois datée, et elle est publiée sur /board.
"""

import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_dashboard_data import build_series  # noqa: E402


CLICKS = [
    {"send_date": "2026-08-01", "article_rank": "1", "target_url": "https://www.lemonde.fr/a"},
    {"send_date": "2026-08-01", "article_rank": "3", "target_url": "https://lemonde.fr/b"},
    {"send_date": "2026-08-02", "article_rank": "1", "target_url": "https://franceinfo.fr/c"},
]
OPENS = [
    {"send_date": "2026-08-01", "email_hash": "aaa"},
    {"send_date": "2026-08-01", "email_hash": "bbb"},
    {"send_date": "2026-08-02", "email_hash": "aaa"},
]
TOPICS = [("2026-08-01", "sport"), ("2026-08-01", "santé"), ("2026-08-02", "sport")]


def test_les_clics_gardent_leur_date_leur_rang_et_leur_domaine():
    s = build_series(clicks=CLICKS, opens=[], topics_by_date=[])
    assert s["clicks"] == [
        ["2026-08-01", 1, "lemonde.fr"],
        ["2026-08-01", 3, "lemonde.fr"],
        ["2026-08-02", 1, "franceinfo.fr"],
    ]


def test_le_prefixe_www_est_retire_pour_ne_pas_scinder_un_domaine():
    s = build_series(clicks=CLICKS, opens=[], topics_by_date=[])
    assert {d for _, _, d in s["clicks"]} == {"lemonde.fr", "franceinfo.fr"}


def test_agreger_toute_la_serie_redonne_le_total_publie():
    """Les deux vues doivent dire la même chose, sinon l'une des deux ment."""
    s = build_series(clicks=CLICKS, opens=[], topics_by_date=[])
    assert Counter(r for _, r, _ in s["clicks"]) == Counter({1: 2, 3: 1})


def test_les_ouvertures_sont_groupees_par_date():
    s = build_series(clicks=[], opens=OPENS, topics_by_date=[])
    assert sorted(s["opens"]) == ["2026-08-01", "2026-08-02"]
    assert len(s["opens"]["2026-08-01"]) == 2


def test_un_lecteur_est_un_indice_jamais_un_identifiant():
    """
    Ces séries partent potentiellement sur /board. Un hash d'adresse y serait
    un identifiant stable — c'est précisément ce que le projet a passé une
    semaine à retirer de ses fichiers.
    """
    s = build_series(clicks=[], opens=OPENS, topics_by_date=[])
    plats = [v for lst in s["opens"].values() for v in lst]
    assert all(isinstance(v, int) for v in plats)
    assert "aaa" not in repr(s)


def test_le_meme_lecteur_garde_le_meme_indice_entre_deux_dates():
    """Sans quoi la fidélité recalculée compterait deux personnes au lieu d'une."""
    s = build_series(clicks=[], opens=OPENS, topics_by_date=[])
    assert s["opens"]["2026-08-01"][0] == s["opens"]["2026-08-02"][0]


def test_la_fidelite_se_recalcule_sur_une_periode():
    s = build_series(clicks=[], opens=OPENS, topics_by_date=[])
    par_lecteur = Counter()
    for jour, lecteurs in s["opens"].items():
        if jour >= "2026-08-02":
            for l in lecteurs:
                par_lecteur[l] += 1
    assert sorted(par_lecteur.values(), reverse=True) == [1]


def test_les_themes_sont_comptes_par_date():
    s = build_series(clicks=[], opens=[], topics_by_date=TOPICS)
    assert s["topics"] == {
        "2026-08-01": {"sport": 1, "santé": 1},
        "2026-08-02": {"sport": 1},
    }


def test_un_theme_absent_devient_indetermine():
    s = build_series(clicks=[], opens=[], topics_by_date=[("2026-08-01", None)])
    assert s["topics"]["2026-08-01"] == {"indéterminé": 1}


def test_un_rang_illisible_ne_fait_pas_tomber_la_construction():
    """Une ligne abîmée ne doit pas priver le tableau de bord de tout l'historique."""
    s = build_series(
        clicks=[{"send_date": "2026-08-01", "article_rank": "", "target_url": "https://x.fr/a"}],
        opens=[], topics_by_date=[])
    assert s["clicks"] == []


# ---------------------------------------------------------------------------
# La liste blanche de /board
#
# `series.opens` est une matrice « lecteur × jour » : bien plus révélatrice que
# le `loyalty` agrégé publié aujourd'hui. Elle dit, pour chaque lecteur, quels
# jours précis il a ouvert la newsletter.
#
# La liste blanche l'exclut par construction — c'est exactement le cas pour
# lequel elle a été écrite. Ce test le constate plutôt que de l'espérer.
# ---------------------------------------------------------------------------

sys.path.insert(0, str(ROOT / "auth_server"))


def test_les_series_ne_partent_pas_sur_le_board():
    from public_board import public_payload

    payload = {
        "generated": "2026-09-01T08:00:00+00:00",
        "editions": [], "runs": [], "unsub": [],
        "loyalty": [3, 1],
        "series": {
            "clicks": [["2026-08-01", 1, "lemonde.fr"]],
            "opens": {"2026-08-01": [0, 1], "2026-08-02": [0]},
            "topics": {"2026-08-01": {"sport": 1}},
            "readers": 2,
        },
    }
    public = public_payload(payload)
    assert "series" not in public
    assert "2026-08-02" not in repr(public), \
        "aucun calendrier d'ouverture par lecteur ne doit sortir"


def test_le_board_garde_la_fidelite_agregee():
    """Exclure les séries ne doit pas appauvrir ce qui était déjà public."""
    from public_board import public_payload

    public = public_payload({
        "generated": "x", "editions": [], "runs": [], "unsub": [],
        "loyalty": [3, 1],
    })
    assert public["loyalty"] == [3, 1]
