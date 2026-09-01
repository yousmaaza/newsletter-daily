"""
Tests du filtrage par période.

Le tableau de bord montrait des moyennes depuis avril. Une moyenne sur cinq
mois ne montre aucune évolution : impossible de voir qu'une semaine décroche.

L'agrégation se fait ici, en Python, plutôt que dans le navigateur. Le coût
est un rechargement de page ; le gain est que chaque règle est vérifiable par
un test — ce projet a appris à ses dépens que ce qui n'est pas regardé n'est
pas su.

⚠️ /dashboard et /board partagent le même gabarit, mais /board reçoit un
payload sans `series` (liste blanche). Le filtre doit donc s'effacer, jamais
échouer.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "auth_server"))

from dashboard_range import RANGES, apply_range, window_start  # noqa: E402

AUJ = date(2026, 9, 1)

PAYLOAD = {
    "series": {
        "clicks": [
            ["2026-06-01", 1, "vieux.fr"],
            ["2026-08-28", 1, "lemonde.fr"],
            ["2026-08-30", 3, "lemonde.fr"],
        ],
        "opens": {
            "2026-06-01": [0, 1],
            "2026-08-28": [0, 1, 2],
            "2026-08-30": [0],
        },
        "topics": {
            "2026-06-01": {"sport": 2},
            "2026-08-28": {"sport": 1, "santé": 1},
        },
        "readers": 3,
    },
    "editions": [
        {"date": "2026-06-01", "sent": 20, "opens": 2, "clicks": 1},
        {"date": "2026-08-28", "sent": 28, "opens": 3, "clicks": 1},
        {"date": "2026-08-30", "sent": 28, "opens": 1, "clicks": 1},
    ],
    "runs": [{"date": "2026-06-01"}, {"date": "2026-08-30"}],
    "unsub": [{"date": "2026-06-01", "reason": "too_long"},
              {"date": "2026-08-30", "reason": "too_frequent"}],
    "by_rank": {"1": 2, "3": 1},
    "by_domain": {"lemonde.fr": 2, "vieux.fr": 1},
    "loyalty": [3, 2, 1],
    "unique_readers": 3,
    "topics": {"config": ["santé"], "counts": {"sport": 3, "santé": 1}, "total": 4},
    "totals": {"editions": 3, "opens": 6, "clicks": 3, "feedback": 0},
}


def test_toute_la_periode_ne_change_rien():
    assert apply_range(PAYLOAD, "all", today=AUJ) == PAYLOAD


def test_une_periode_inconnue_ne_change_rien():
    """Un paramètre d'URL trafiqué ne doit pas produire une page vide."""
    assert apply_range(PAYLOAD, "n-importe-quoi", today=AUJ) == PAYLOAD


def test_un_payload_sans_series_traverse_intact():
    """C'est le cas de /board : le filtre s'efface au lieu d'échouer."""
    public = {k: v for k, v in PAYLOAD.items() if k != "series"}
    assert apply_range(public, "7d", today=AUJ) == public


def test_les_clics_hors_periode_sortent_du_classement():
    out = apply_range(PAYLOAD, "1m", today=AUJ)
    assert out["by_rank"] == {"1": 1, "3": 1}
    assert out["by_domain"] == {"lemonde.fr": 2}


def test_les_editions_hors_periode_disparaissent():
    out = apply_range(PAYLOAD, "1m", today=AUJ)
    assert [e["date"] for e in out["editions"]] == ["2026-08-28", "2026-08-30"]


def test_les_runs_et_les_departs_suivent_la_meme_periode():
    """Un filtre qui ne s'applique qu'à une moitié de la page est un piège."""
    out = apply_range(PAYLOAD, "1m", today=AUJ)
    assert [r["date"] for r in out["runs"]] == ["2026-08-30"]
    assert [u["date"] for u in out["unsub"]] == ["2026-08-30"]
    assert out["unsub_reasons"] == {"too_frequent": 1}


def test_la_fidelite_est_recalculee_sur_la_periode():
    out = apply_range(PAYLOAD, "1m", today=AUJ)
    assert out["loyalty"] == [2, 1, 1]
    assert out["unique_readers"] == 3


def test_un_lecteur_inactif_sur_la_periode_nest_pas_compte():
    """
    Un lecteur sans ouverture sur la fenêtre ne doit pas y figurer avec un
    zéro : la distribution dirait alors qu'il y a plus de lecteurs tièdes
    qu'en réalité. Fenêtre choisie pour ne contenir que le 30 août, où seul
    le lecteur 0 a ouvert.
    """
    out = apply_range(PAYLOAD, "7d", today=date(2026, 9, 5))
    assert out["unique_readers"] == 1
    assert out["loyalty"] == [1]


def test_la_fenetre_de_sept_jours_remonte_bien_a_sept_jours():
    """Depuis le 1er septembre, elle commence le 26 août — le 28 en fait partie."""
    out = apply_range(PAYLOAD, "7d", today=AUJ)
    assert out["unique_readers"] == 3
    assert out["loyalty"] == [2, 1, 1]


def test_les_themes_sont_recalcules():
    out = apply_range(PAYLOAD, "1m", today=AUJ)
    assert out["topics"]["counts"] == {"sport": 1, "santé": 1}
    assert out["topics"]["total"] == 2
    assert out["topics"]["config"] == ["santé"], "la configuration ne dépend pas de la période"


def test_les_totaux_suivent():
    out = apply_range(PAYLOAD, "1m", today=AUJ)
    assert out["totals"]["editions"] == 2
    assert out["totals"]["opens"] == 4
    assert out["totals"]["clicks"] == 2


def test_la_periode_retenue_est_annoncee_dans_le_payload():
    """La page doit pouvoir dire ce qu'elle montre, sinon le chiffre est trompeur."""
    out = apply_range(PAYLOAD, "1m", today=AUJ)
    assert out["range"]["key"] == "1m"
    assert out["range"]["start"] == "2026-08-03", "30 jours inclusifs, borne comprise"


def test_le_payload_dorigine_nest_pas_modifie():
    avant = PAYLOAD["by_rank"].copy()
    apply_range(PAYLOAD, "7d", today=AUJ)
    assert PAYLOAD["by_rank"] == avant


def test_les_bornes_sont_inclusives():
    debut = window_start("7d", today=AUJ)
    assert debut == date(2026, 8, 26)
    assert RANGES["7d"] == 7
