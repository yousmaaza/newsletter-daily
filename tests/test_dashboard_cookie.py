"""
Le jeton sort de l'URL.

Il y voyage depuis toujours : barre d'adresse, historique du navigateur, et
toute capture d'écran. Il a fuité deux fois — la seconde en m'envoyant une
capture pour me montrer la page.

Il a aussi produit un bogue bloquant : un lien de période écrit « ?range=7d »
remplaçait la chaîne de requête entière et emportait le jeton avec elle.
Tant qu'un secret circule dans l'URL, chaque lien interne est une occasion de
le perdre.

Le principe : on ouvre une fois avec ?token=, le serveur pose un cookie et
redirige vers une URL propre. Ensuite, plus rien à préserver.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

JETON = "jeton-de-test"
PAYLOAD = {
    "generated": "2026-09-01T08:00:00+00:00",
    "editions": [{"date": "2026-09-01", "sent": 27, "opens": 11, "clicks": 1}],
    "runs": [], "unsub": [], "by_rank": {}, "by_domain": {},
    "loyalty": [1], "unique_readers": 1, "unsub_reasons": {},
    "topics": {"config": [], "counts": {}, "total": 0},
    "totals": {"editions": 1, "opens": 11, "clicks": 1, "feedback": 0},
}


@pytest.fixture
def client(monkeypatch):
    for k, v in {"GITHUB_TOKEN": "ghp_fake", "GITHUB_REPO": "u/r",
                 "STATS_TOKEN": JETON, "GOOGLE_CLIENT_ID": "x",
                 "GOOGLE_CLIENT_SECRET": "x", "UNSUBSCRIBE_SECRET": "x",
                 "AUTH_SERVER_URL": "http://localhost"}.items():
        monkeypatch.setenv(k, v)
    import app as flask_app
    monkeypatch.setattr(flask_app, "build_dashboard_payload",
                        lambda *a, **k: json.loads(json.dumps(PAYLOAD)))
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_le_jeton_en_url_pose_un_cookie_et_redirige(client):
    r = client.get(f"/dashboard?token={JETON}")
    assert r.status_code == 302
    assert "stats_session" in r.headers.get("Set-Cookie", "")


def test_lurl_de_redirection_ne_contient_plus_le_jeton(client):
    """Tout l'intérêt : la barre d'adresse et l'historique redeviennent propres."""
    r = client.get(f"/dashboard?token={JETON}")
    assert JETON not in r.headers["Location"]
    assert "token" not in r.headers["Location"]


def test_la_redirection_conserve_la_periode(client):
    """Sinon, ouvrir un lien partagé sur « 3 mois » retomberait sur « tout »."""
    r = client.get(f"/dashboard?token={JETON}&range=3m")
    assert "range=3m" in r.headers["Location"]


def test_le_cookie_est_inaccessible_au_javascript(client):
    """HttpOnly : un script injecté dans la page ne doit pas pouvoir le lire."""
    r = client.get(f"/dashboard?token={JETON}")
    assert "HttpOnly" in r.headers["Set-Cookie"]


def test_le_cookie_seul_suffit_ensuite(client):
    client.get(f"/dashboard?token={JETON}")
    assert client.get("/dashboard").status_code == 200


def test_la_route_json_accepte_le_cookie(client):
    """Le rafraîchissement automatique n'a plus de jeton à transmettre."""
    client.get(f"/dashboard?token={JETON}")
    assert client.get("/dashboard/data").status_code == 200


def test_sans_cookie_ni_jeton_laccès_est_refusé(client):
    assert client.get("/dashboard").status_code == 401
    assert client.get("/dashboard/data").status_code == 401


def test_un_cookie_invalide_est_refusé(client):
    client.set_cookie("stats_session", "pas-le-bon", domain="localhost")
    assert client.get("/dashboard").status_code == 401


def test_la_page_de_stats_redirige_vers_le_tableau_de_bord(client):
    """
    Les deux pages disaient la même chose dans deux styles différents. /stats
    est conservée en redirection : des liens circulent, et une page qui
    disparaît sans rediriger est une page qui casse.
    """
    r = client.get("/stats/2026-08-27")
    assert r.status_code == 302
    assert r.headers["Location"] == "/dashboard/2026-08-27"


def test_un_vieux_lien_stats_avec_jeton_ouvre_la_session(client):
    """Sinon un lien encore en circulation redirigerait vers un refus."""
    r = client.get(f"/stats/2026-08-27?token={JETON}")
    assert r.status_code == 302
    assert "stats_session" in r.headers.get("Set-Cookie", "")


def test_une_date_invalide_est_refusee_avant_toute_redirection(client):
    assert client.get("/stats/pas-une-date").status_code == 400
    assert client.get("/dashboard/pas-une-date").status_code == 400


def test_le_board_public_reste_sans_jeton(client):
    """/board est la page que la newsletter annonce à ses lecteurs."""
    assert client.get("/board").status_code == 200


def test_le_cookie_est_marque_secure_derriere_un_terminateur_tls(client):
    """
    Railway termine TLS en amont : le schéma vu par Flask est http, alors que
    la connexion réelle est chiffrée. Sans lire X-Forwarded-Proto, le cookie
    ne serait jamais marqué Secure en production — et pourrait voyager en
    clair si quelqu'un atteignait le service en http.
    """
    r = client.get(f"/dashboard?token={JETON}", headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in r.headers["Set-Cookie"]


def test_le_cookie_nest_pas_secure_en_clair(client):
    """Sinon le développement local ne pourrait pas ouvrir de session."""
    r = client.get(f"/dashboard?token={JETON}")
    assert "Secure" not in r.headers["Set-Cookie"]


def test_une_periode_inconnue_ne_survit_pas_a_la_redirection(client):
    """
    La cible de redirection est construite à partir du paramètre reçu : y
    recopier n'importe quoi ouvrirait une porte à l'injection.
    """
    r = client.get(f"/dashboard?token={JETON}&range=../../evil")
    assert r.headers["Location"] == "/dashboard"
