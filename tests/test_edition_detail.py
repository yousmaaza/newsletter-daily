"""
Détail d'une édition — extrait de la route /stats pour être partagé.

/dashboard et /stats calculaient la même chose de deux façons, dans deux
pages au style différent. Fusionner impose d'abord d'extraire le calcul :
tant qu'il vit dans le corps d'une route, il n'est ni réutilisable ni
testable sans réseau.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "auth_server"))

from edition_detail import build_detail  # noqa: E402


def detail(**kw):
    base = dict(send_date="2026-09-01", sent=27, opens=[], reactions=[],
                clicks=[], feedbacks=[], articles=[])
    base.update(kw)
    return build_detail(**base)


ARTICLES = [{"rank": 1, "title": "La batterie quantique"},
            {"rank": 2, "title": "Rentrée 2026"},
            {"rank": 3, "title": "Science en revue"}]


def test_un_article_sans_interaction_figure_quand_meme():
    """
    Sinon la page ne montrerait que les articles qui ont marché, et l'absence
    de signal — le tiers de l'édition que personne n'ouvre — disparaîtrait.
    """
    d = detail(articles=ARTICLES)
    assert [a["rank"] for a in d["articles"]] == [1, 2, 3]
    assert all(a["clicks"] == 0 for a in d["articles"])


def test_les_articles_sont_classes_par_score_decroissant():
    d = detail(articles=ARTICLES,
               clicks=[{"article_rank": "2", "email_hash": "a"}],
               reactions=[{"article_rank": "3", "reaction": "like", "email_hash": "b"}])
    assert [a["rank"] for a in d["articles"]] == [3, 2, 1]


def test_le_score_pondere_les_signaux():
    """Un clic vaut 2, un pouce levé 3, un mitigé 1 — rapportés aux envoyés."""
    d = detail(sent=100, articles=[{"rank": 1, "title": "x"}],
               clicks=[{"article_rank": "1", "email_hash": "a"}],
               reactions=[{"article_rank": "1", "reaction": "like", "email_hash": "b"}])
    assert d["articles"][0]["score"] == 5.0


def test_une_edition_sans_destinataire_ne_divise_pas_par_zero():
    d = detail(sent=0, articles=[{"rank": 1, "title": "x"}],
               clicks=[{"article_rank": "1", "email_hash": "a"}])
    assert d["articles"][0]["score"] >= 0


def test_un_signal_sur_un_rang_absent_de_larchive_apparait():
    """
    L'archive peut manquer — le pipeline l'a déjà écrite deux fois. Perdre un
    clic parce que son article n'est pas listé serait pire que d'afficher un
    titre générique.
    """
    d = detail(articles=[], clicks=[{"article_rank": "7", "email_hash": "a"}])
    assert [a["rank"] for a in d["articles"]] == [7]
    assert "7" in d["articles"][0]["title"]


def test_les_lecteurs_sont_comptes_une_fois():
    d = detail(opens=[{"email_hash": "a"}, {"email_hash": "a"}, {"email_hash": "b"}],
               clicks=[{"article_rank": "1", "email_hash": "a"},
                       {"article_rank": "2", "email_hash": "a"}])
    assert d["opens"] == 2
    assert d["clickers"] == 1


def test_seuls_les_commentaires_non_vides_sont_retenus():
    d = detail(feedbacks=[{"comment": "  ", "email_hash": "a"},
                          {"comment": "Bien", "email_hash": "b"}])
    assert d["comments"] == ["Bien"]


def test_les_reactions_globales_sont_comptees():
    d = detail(feedbacks=[{"global_reaction": "like", "email_hash": "a"},
                          {"global_reaction": "meh", "email_hash": "b"},
                          {"global_reaction": "like", "email_hash": "c"}])
    assert d["global"] == {"like": 2, "meh": 1, "dislike": 0}


def test_le_detail_porte_sa_date():
    """La page doit pouvoir dire de quelle édition elle parle."""
    assert detail(send_date="2026-08-27")["date"] == "2026-08-27"
