"""
La route JSON doit honorer la période, comme la route HTML.

Constaté en production le 1er septembre : on pouvait choisir une période, et
elle se défaisait toute seule dans la minute.

`/dashboard` appliquait le filtre, `/dashboard/data` non. Le rafraîchissement
automatique — toutes les minutes, et à chaque retour sur l'onglet — remplaçait
le payload entier par la version non filtrée, puis redessinait. Le sélecteur
restait sur « 7 jours » pendant que les chiffres revenaient à tout
l'historique : le pire des deux états, parce que rien ne le signalait.

C'est le défaut typique de ce projet : correct au moment où on le regarde,
faux une minute plus tard.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

PAYLOAD = {
    "generated": "2026-09-01T08:00:00+00:00",
    "series": {
        "clicks": [["2026-01-01", 1, "vieux.fr"], ["2026-09-01", 2, "recent.fr"]],
        "opens": {"2026-01-01": [0], "2026-09-01": [0, 1]},
        "topics": {"2026-09-01": {"sport": 1}},
        "readers": 2,
    },
    "editions": [{"date": "2026-01-01", "sent": 10, "opens": 1, "clicks": 1},
                 {"date": "2026-09-01", "sent": 27, "opens": 2, "clicks": 1}],
    "runs": [], "unsub": [],
    "by_rank": {"1": 1, "2": 1},
    "by_domain": {"vieux.fr": 1, "recent.fr": 1},
    "loyalty": [2, 1], "unique_readers": 2,
    "topics": {"config": [], "counts": {"sport": 1}, "total": 1},
    "totals": {"editions": 2, "opens": 3, "clicks": 2, "feedback": 0},
}


@pytest.fixture
def client(monkeypatch):
    for k, v in {"GITHUB_TOKEN": "ghp_fake", "GITHUB_REPO": "u/r",
                 "STATS_TOKEN": "jeton", "GOOGLE_CLIENT_ID": "x",
                 "GOOGLE_CLIENT_SECRET": "x", "UNSUBSCRIBE_SECRET": "x",
                 "AUTH_SERVER_URL": "http://localhost"}.items():
        monkeypatch.setenv(k, v)
    import app as flask_app
    monkeypatch.setattr(flask_app, "build_dashboard_payload", lambda *a, **k: json.loads(json.dumps(PAYLOAD)))
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_la_route_json_applique_la_periode(client):
    r = client.get("/dashboard/data?token=jeton&range=7d")
    assert r.status_code == 200
    assert r.get_json()["range"]["key"] == "7d"


def test_sans_periode_la_route_json_rend_tout(client):
    r = client.get("/dashboard/data?token=jeton")
    assert r.status_code == 200
    assert "range" not in r.get_json()
    assert r.get_json()["totals"]["editions"] == 2


def test_les_deux_routes_saccordent_sur_la_meme_periode(client):
    """
    Si elles divergent, le rafraîchissement défait le choix de l'utilisateur
    sans rien signaler — les chiffres changent, le sélecteur ne bouge pas.
    """
    # Le jeton en URL ouvre une session et redirige : on suit jusqu'à la page.
    html = client.get("/dashboard?token=jeton&range=7d", follow_redirects=True)
    data = client.get("/dashboard/data?range=7d").get_json()
    assert html.status_code == 200
    injecte = json.loads(html.get_data(as_text=True)
                         .split('id="pulse-data" type="application/json">')[1]
                         .split("</script>")[0])
    assert injecte["range"] == data["range"]
    assert injecte["totals"]["editions"] == data["totals"]["editions"]
    assert injecte["by_rank"] == data["by_rank"]


def test_la_page_redemande_ses_donnees_avec_la_periode_courante():
    """
    La route peut bien accepter le paramètre : si la page ne le renvoie pas au
    rafraîchissement, le filtre se défait quand même.
    """
    src = (ROOT / "auth_server" / "dashboard.html").read_text(encoding="utf-8")
    assert 'q.set("range", D.range.key)' in src


def test_le_jeton_nest_transmis_que_sil_est_encore_dans_lurl():
    """Une fois la session en cookie, le navigateur s'en charge seul."""
    src = (ROOT / "auth_server" / "dashboard.html").read_text(encoding="utf-8")
    assert 'if (TOKEN) q.set("token", TOKEN);' in src


# ---------------------------------------------------------------------------
# Les liens de période doivent conserver le reste de l'URL
#
# Premier jet : href="?range=7d". Une chaîne de requête qui commence par « ? »
# remplace la précédente en entier — le jeton partait avec, et cliquer sur une
# période rendait la page inaccessible.
#
# Tant que le jeton voyage dans l'URL, tout lien interne doit la reconstruire
# plutôt que la réécrire.
# ---------------------------------------------------------------------------


def test_les_liens_de_periode_conservent_le_jeton():
    src = (ROOT / "auth_server" / "dashboard.html").read_text(encoding="utf-8")
    assert 'new URL(window.location.href)' in src, \
        "le lien doit partir de l'URL courante, pas d'une chaîne « ?range= » nue"
    assert 'searchParams.set("range"' in src
    assert '\'<a href="?range=\'' not in src and "'?range=' + k" not in src, \
        "une chaîne de requête nue écrase le jeton"
