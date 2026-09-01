"""
Génère les URLs signées HMAC pour les interactions article (réaction, clic, pixel).

- Le lecteur est désigné par un identifiant OPAQUE, tiré au sort et stocké dans
  config/subscriber_ids.toml — jamais par son adresse ni par un hash de celle-ci.
- Token HMAC couvre : identifiant:date pour le pixel,
                      identifiant:date:article_rank pour réaction et clic

Historique : jusqu'au 26 août 2026, l'identifiant était un SHA-256 NON SALÉ de
l'adresse. Avec la liste d'abonnés en main, il se retournait par simple
comparaison — 23 des 26 identifiants présents dans data/ ont été ré-identifiés
en quelques millisecondes lors de l'audit. Voir tools/subscriber_ids.py.
"""

import hashlib
import hmac
import urllib.parse

from tools.subscriber_ids import SubscriberIds

_STORE: SubscriberIds | None = None


def _subscriber_ids() -> SubscriberIds:
    """Table de correspondance, chargée une seule fois par processus."""
    global _STORE
    if _STORE is None:
        _STORE = SubscriberIds()
    return _STORE


def _hash_email(email: str) -> str:
    """
    Identifiant opaque du lecteur, créé à la volée s'il est nouveau.

    Le nom est conservé pour ne pas toucher aux quatre appelants ci-dessous ;
    la valeur retournée n'a plus rien d'un hash.
    """
    return _subscriber_ids().get_or_create(email)


def _make_token(secret: str, *parts: str) -> str:
    payload = ":".join(parts)
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def build_pixel_url(base_url: str, email: str, send_date: str, secret: str) -> str:
    eh = _hash_email(email)
    token = _make_token(secret, eh, send_date)
    params = urllib.parse.urlencode({"email": eh, "date": send_date, "token": token})
    return f"{base_url.rstrip('/')}/pixel?{params}"


def build_reaction_url(
    base_url: str,
    email: str,
    send_date: str,
    article_rank: int,
    reaction: str,
    secret: str,
) -> str:
    """reaction : 'like' | 'meh' | 'dislike'"""
    eh = _hash_email(email)
    token = _make_token(secret, eh, send_date, str(article_rank))
    params = urllib.parse.urlencode({
        "email": eh,
        "date": send_date,
        "article": article_rank,
        "r": reaction,
        "token": token,
    })
    return f"{base_url.rstrip('/')}/react?{params}"


def build_click_url(
    base_url: str,
    email: str,
    send_date: str,
    article_rank: int,
    target_url: str,
    secret: str,
) -> str:
    eh = _hash_email(email)
    token = _make_token(secret, eh, send_date, str(article_rank))
    params = urllib.parse.urlencode({
        "email": eh,
        "date": send_date,
        "article": article_rank,
        "url": target_url,
        "token": token,
    })
    return f"{base_url.rstrip('/')}/click?{params}"


def build_feedback_url(
    base_url: str,
    email: str,
    send_date: str,
    global_reaction: str,
    secret: str,
) -> str:
    """global_reaction : 'like' | 'meh' | 'dislike'"""
    eh = _hash_email(email)
    token = _make_token(secret, eh, send_date)
    params = urllib.parse.urlencode({
        "email": eh,
        "date": send_date,
        "global": global_reaction,
        "token": token,
    })
    return f"{base_url.rstrip('/')}/feedback?{params}"
