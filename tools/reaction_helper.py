"""
Construit les URLs signées pour le pixel de tracking, les réactions et les notes.
Réutilise le même HMAC que unsubscribe_helper (token = HMAC(email:date, secret)).
"""

import urllib.parse

from tools.unsubscribe_helper import generate_token


def build_pixel_url(auth_server_url: str, email: str, send_date: str, secret: str) -> str:
    token = generate_token(email, send_date, secret)
    params = urllib.parse.urlencode({"email": email, "date": send_date, "token": token})
    return f"{auth_server_url.rstrip('/')}/pixel?{params}"


def build_reaction_base(auth_server_url: str, email: str, send_date: str, secret: str) -> str:
    """Base URL des boutons réaction — compléter avec &article=N&r=fire."""
    token = generate_token(email, send_date, secret)
    params = urllib.parse.urlencode({"email": email, "date": send_date, "token": token})
    return f"{auth_server_url.rstrip('/')}/react?{params}"


def build_rating_base(auth_server_url: str, email: str, send_date: str, secret: str) -> str:
    """Base URL des étoiles — compléter avec &stars=N."""
    token = generate_token(email, send_date, secret)
    params = urllib.parse.urlencode({"email": email, "date": send_date, "token": token})
    return f"{auth_server_url.rstrip('/')}/rate?{params}"
