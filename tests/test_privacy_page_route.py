"""
Tests de la page vie privée servie par auth_server.

C'est la page que le bloc transparence annonce aux lecteurs. Elle doit être
lisible sans authentification, indexable, et rester servie même si la
configuration GitHub est absente — une page d'information ne doit pas dépendre
de l'infrastructure de mesure qu'elle décrit.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("STATS_TOKEN", raising=False)

    import app as flask_app

    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_the_page_is_served_without_authentication(client):
    assert client.get("/vie-privee").status_code == 200


def test_the_page_does_not_depend_on_github_being_configured(client):
    """Une page d'information ne doit pas tomber avec l'infrastructure de mesure."""
    assert client.get("/vie-privee").status_code == 200


def test_the_page_is_indexable(client):
    """Contrairement à /dashboard, elle a vocation à être trouvée."""
    assert "X-Robots-Tag" not in client.get("/vie-privee").headers


def test_the_page_is_html(client):
    assert "text/html" in client.get("/vie-privee").headers["Content-Type"]


def test_the_page_states_what_is_collected(client):
    body = client.get("/vie-privee").get_data(as_text=True)

    assert "Ce que je mesure" in body
    assert "Ce que je collecte" in body


def test_the_page_explains_how_to_refuse(client):
    body = client.get("/vie-privee").get_data(as_text=True)

    assert "Vos droits" in body
    assert "mesur" in body


def test_the_page_mentions_the_supervisory_authority(client):
    """Le recours doit être indiqué, pas seulement les droits."""
    assert "cnil.fr" in client.get("/vie-privee").get_data(as_text=True)


def test_the_page_links_to_the_public_board(client):
    assert "/board" in client.get("/vie-privee").get_data(as_text=True)


def test_no_subscriber_address_appears_on_the_page(client):
    """La page parle de données personnelles, elle ne doit pas en contenir."""
    import re

    body = client.get("/vie-privee").get_data(as_text=True)
    found = set(re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", body, re.I))

    assert not found, f"adresses présentes sur la page : {found}"
