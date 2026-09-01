"""
Tests de la page d'inscription servie par auth_server.

Cette page ne fait qu'une chose : afficher un formulaire qui poste vers Google
Forms. Toute la logique d'inscription — déduplication, filtrage des désinscrits,
réinscription — reste dans `sync_recipients.gs`, inchangée.

Le risque propre à ce montage est qu'il échoue *poliment* : Google ne renvoie
pas d'en-tête CORS, la réponse part dans une iframe cachée, et le navigateur ne
peut pas lire ce qui s'est passé. La page remercie donc sans preuve. C'est
tenable tant que le formulaire est correctement câblé — et intenable sinon,
d'où le garde-fou vérifié ici.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "auth_server"))

LANDING = ROOT / "auth_server" / "landing.html"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("STATS_TOKEN", raising=False)

    import app as flask_app

    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


@pytest.fixture
def unconfigured(monkeypatch, tmp_path):
    """Sert une copie de la page ramenée à ses placeholders."""
    import app as flask_app

    html = LANDING.read_text(encoding="utf-8")
    html = re.sub(r"/e/1FAIpQLSc[\w-]+/", "/e/FORM_ID/", html)

    target = tmp_path / "landing.html"
    target.write_text(html, encoding="utf-8")
    monkeypatch.setattr(flask_app, "LANDING_TEMPLATE", target)
    return target


# ── Le garde-fou : jamais de page qui remercie sans enregistrer ─────────────

def test_an_unconfigured_page_is_refused(client, unconfigured):
    """
    Avec un FORM_ID non remplacé, la soumission part vers une URL inexistante
    et l'iframe avale l'erreur : le visiteur serait remercié, son adresse
    perdue. Mieux vaut ne rien servir.
    """
    assert client.get("/inscription").status_code == 503


def test_the_page_is_served(client):
    assert client.get("/inscription").status_code == 200


def test_the_page_is_served_without_authentication(client):
    assert client.get("/inscription").status_code == 200


def test_the_page_does_not_depend_on_github_being_configured(client):
    """Elle ne lit ni n'écrit aucune donnée : elle sert un fichier."""
    assert client.get("/inscription").status_code == 200


def test_the_page_is_indexable(client):
    """Une page d'inscription a vocation à être trouvée."""
    assert "X-Robots-Tag" not in client.get("/inscription").headers


def test_the_page_is_html(client):
    assert "text/html" in client.get("/inscription").headers["Content-Type"]


# ── Ce que la page doit contenir pour tenir sa promesse ────────────────────

def test_the_form_posts_to_google_forms(client):
    """
    C'est tout l'intérêt du montage : Apps Script reste le seul écrivain de
    recipients.toml. Un formulaire qui posterait ailleurs contournerait le
    filtrage des désinscrits.
    """
    body = client.get("/inscription").get_data(as_text=True)

    assert "docs.google.com/forms/" in body
    assert "/formResponse" in body


def test_the_page_never_writes_anything(client):
    """Aucune route d'écriture ne doit être atteignable depuis ce formulaire."""
    body = client.get("/inscription").get_data(as_text=True)

    for route in ("/unsubscribe", "/tracking-optout", "/react", "/click"):
        assert f'action="{route}' not in body


def test_the_page_announces_the_measurement(client):
    """
    La lettre annonce ce qu'elle mesure dans chaque édition ; la page qui
    recrute ne peut pas être moins claire que l'email qu'elle promet.
    """
    body = client.get("/inscription").get_data(as_text=True)

    assert "/vie-privee" in body
    assert "/board" in body


def test_the_page_states_how_to_leave(client):
    """On ne demande pas une adresse sans dire comment la reprendre."""
    body = client.get("/inscription").get_data(as_text=True).lower()

    assert "désinscription" in body or "désabonner" in body


def test_no_subscriber_address_appears_on_the_page(client):
    """La page collecte des adresses, elle ne doit pas en exposer."""
    body = client.get("/inscription").get_data(as_text=True)
    found = {
        m for m in re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", body, re.I)
        if not m.endswith("@exemple.fr")          # le placeholder du champ
    }

    assert not found, f"adresses présentes sur la page : {found}"


# ── Le fichier versionné, lui, reste vierge de configuration ───────────────

def test_the_committed_file_is_configured():
    """
    Le projet n'a qu'un déploiement et qu'un formulaire, et son identifiant
    est public — il figure dans l'URL du formulaire comme dans la page servie.
    Le committer évite une étape de configuration au déploiement, donc une
    occasion de servir la page muette.

    L'identifiant attendu est celui des RÉPONSES (`/forms/d/e/1FAIpQLSc…`).
    Celui de l'édition (`/forms/d/<id>/edit`) donne un 404 que l'iframe
    avalerait sans rien dire.
    """
    html = LANDING.read_text(encoding="utf-8")

    assert "/e/FORM_ID/" not in html, "placeholder non remplacé"
    assert "entry.000000000" not in html, "champ email non configuré"
    assert re.search(r"/forms/d/e/1FAIpQLSc[\w-]{20,}/formResponse", html)
    assert re.search(r'name="entry\.\d{6,}"', html)


def test_the_two_forms_target_the_same_place():
    """
    La page porte deux formulaires, en haut et en bas. Une divergence entre
    les deux enverrait la moitié des inscriptions dans le vide.
    """
    html = LANDING.read_text(encoding="utf-8")

    assert len(set(re.findall(r'action="([^"]+formResponse)"', html))) == 1
    assert len(set(re.findall(r'name="(entry\.\d+)"', html))) == 1


def test_the_committed_file_carries_a_honeypot():
    """
    Poster directement contourne le reCAPTCHA du formulaire. Le champ piège
    est la seule barrière restante contre les robots élémentaires.
    """
    html = LANDING.read_text(encoding="utf-8")

    assert 'name="site"' in html
    assert 'class="hp"' in html


def test_the_honeypot_actually_blocks_the_submission():
    """
    Un champ piège que personne ne lit est un ornement. La première version
    de cette page en avait un : présent dans le formulaire, jamais vérifié,
    et la soumission partait quand même.
    """
    html = LANDING.read_text(encoding="utf-8")

    assert 'input[name="site"]' in html, "le piège n'est jamais lu"
    assert "preventDefault()" in html, "le piège ne bloque rien"


def test_a_caught_bot_is_still_shown_the_confirmation():
    """
    Annuler l'envoi *et* afficher une erreur apprendrait au robot qu'il a été
    repéré. La confirmation s'affiche dans les deux cas.
    """
    html = LANDING.read_text(encoding="utf-8")
    script = html[html.index("<script>"):]

    # Le preventDefault est dans une branche fermée avant l'affichage,
    # qui reste donc sur le chemin commun.
    assert script.index("preventDefault()") < script.index('classList.add("sent")')


def test_the_honeypot_needs_no_configuration():
    """
    Il n'atteint jamais Google, donc son nom n'a pas à correspondre à un champ
    du formulaire — une valeur de moins à remplir au déploiement.
    """
    html = LANDING.read_text(encoding="utf-8")

    assert "entry.999999999" not in html
