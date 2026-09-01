"""
Tests de la route HTTP /tracking-optout.

L'écriture GitHub est remplacée par une capture en mémoire : on veut vérifier
le contrôle d'accès et les réponses, pas l'API GitHub.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

SECRET = "s3cr3t"
TODAY = date.today().strftime("%Y-%m-%d")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", SECRET)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    monkeypatch.setenv("GITHUB_REPO", "user/repo")

    import app as flask_app

    recorded: list[str] = []

    def fake_add(email, github_token, github_repo):
        first_time = email not in recorded
        recorded.append(email)
        return first_time

    monkeypatch.setattr(flask_app, "add_to_tracking_optout", fake_add)
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        c.recorded = recorded
        yield c


def _url(email=None, day=None, token=None):
    from auth_server.tracking_optout import generate_optout_token

    email = email or "a@example.com"
    day = day or TODAY
    token = token if token is not None else generate_optout_token(email, day, SECRET)
    return f"/tracking-optout?email={email}&date={day}&token={token}"


def test_a_valid_link_disables_tracking(client):
    response = client.get(_url())

    assert response.status_code == 200
    assert "plus mesur" in response.get_data(as_text=True)
    assert client.recorded == ["a@example.com"]


def test_the_confirmation_says_the_reader_stays_subscribed(client):
    body = client.get(_url()).get_data(as_text=True)

    assert "restez abonn" in body


def test_a_forged_token_is_refused_and_writes_nothing(client):
    response = client.get(_url(token="0" * 64))

    assert response.status_code == 400
    assert client.recorded == []


def test_an_unsubscribe_token_is_refused_on_this_route(client):
    from auth_server.unsubscribe import generate_token

    response = client.get(_url(token=generate_token("a@example.com", TODAY, SECRET)))

    assert response.status_code == 400
    assert client.recorded == []


def test_missing_parameters_are_refused(client):
    assert client.get("/tracking-optout").status_code == 400
    assert client.recorded == []


def test_an_expired_link_is_refused(client):
    old = (date.today() - timedelta(days=91)).strftime("%Y-%m-%d")

    assert client.get(_url(day=old)).status_code == 400
    assert client.recorded == []


def test_clicking_twice_is_idempotent_and_reports_it(client):
    import html

    first = client.get(_url()).get_data(as_text=True)
    second_response = client.get(_url())
    second = html.unescape(second_response.get_data(as_text=True))

    assert second_response.status_code == 200
    assert "déjà actif" in second          # la seconde visite le signale
    assert "déjà actif" not in html.unescape(first)   # ...la première non
