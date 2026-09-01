"""
Tests des routes HTTP /board et /board/data.

Vérifie l'absence de jeton, l'indexabilité, et surtout qu'aucune donnée
sensible ne franchit la route même si le dashboard privé en produit.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

# Un payload « pollué » : il contient tout ce qui ne doit jamais sortir.
DIRTY_PAYLOAD = {
    "generated": "2026-08-25T19:18:30+00:00",
    "editions": [{"date": "2026-08-25", "opens": 17}],
    "totals": {"opens": 1706, "clicks": 168},
    "unique_readers": 26,
    "loyalty": [100, 99, 3, 1],
    "runs": [{"url": "https://github.com/yousmaaza/newletter-ai/actions/runs/1"}],
    "per_reader": {"4d8323e4ff8ba2f2c1": ["2026-08-25"]},
    "subscribers": ["abonnee@exemple.fr"],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    monkeypatch.setenv("GITHUB_REPO", "user/repo")

    import app as flask_app

    monkeypatch.setattr(flask_app, "build_dashboard_payload", lambda *a, **k: dict(DIRTY_PAYLOAD))
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_the_board_is_reachable_without_a_token(client):
    assert client.get("/board").status_code == 200


def test_the_json_is_reachable_without_a_token(client):
    assert client.get("/board/data").status_code == 200


def test_no_email_address_reaches_the_public_json(client):
    body = client.get("/board/data").get_data(as_text=True)

    assert "exemple.fr" not in body
    assert "@" not in body


def test_no_reader_identifier_reaches_the_public_json(client):
    body = client.get("/board/data").get_data(as_text=True)

    assert "4d8323e4ff8ba2f2c1" not in body
    assert "per_reader" not in body


def test_the_github_repository_is_not_disclosed(client):
    body = client.get("/board/data").get_data(as_text=True)

    assert "github.com" not in body
    assert "yousmaaza" not in body


def test_the_aggregates_do_reach_the_public_json(client):
    payload = json.loads(client.get("/board/data").get_data(as_text=True))

    assert payload["unique_readers"] == 26
    assert payload["totals"]["opens"] == 1706
    assert payload["loyalty"] == [100, 99, 3, 1]


def test_the_html_page_embeds_only_filtered_data(client):
    body = client.get("/board").get_data(as_text=True)

    assert "exemple.fr" not in body
    assert "per_reader" not in body


def test_the_public_page_is_indexable(client):
    """Contrairement à /dashboard, cette page a vocation à être trouvée."""
    assert "X-Robots-Tag" not in client.get("/board").headers


def test_the_private_dashboard_still_demands_its_token(client):
    assert client.get("/dashboard").status_code in (401, 503)
