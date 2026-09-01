"""
Unsubscribe token helpers — côté envoi de newsletter.
Utilisé par agent.py et gmail_tool.py pour générer les URLs de désinscription.
"""

import hashlib
import hmac
import urllib.parse
from datetime import date


def generate_token(email: str, send_date: str, secret: str) -> str:
    """HMAC-SHA256 de 'email:send_date'. Retourne un hex string URL-safe."""
    payload = f"{email.lower()}:{send_date}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def build_unsubscribe_url(base_url: str, email: str, send_date: str, secret: str) -> str:
    """Construit l'URL de désinscription signée pour un destinataire."""
    token = generate_token(email, send_date, secret)
    params = urllib.parse.urlencode({"email": email, "date": send_date, "token": token})
    return f"{base_url.rstrip('/')}/unsubscribe?{params}"


def generate_optout_token(email: str, send_date: str, secret: str) -> str:
    """
    HMAC-SHA256 de 'optout:email:send_date'.

    Le préfixe rend le jeton distinct de celui de désinscription : un lien capté
    dans un email ne permet pas de déclencher l'autre action sur le même abonné.
    """
    payload = f"optout:{email.lower()}:{send_date}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def build_tracking_optout_url(base_url: str, email: str, send_date: str, secret: str) -> str:
    """
    Construit l'URL signée « ne plus être mesuré ».

    Action distincte de la désinscription : l'abonné reste destinataire de la
    newsletter, seule la mesure d'audience s'arrête pour lui.
    """
    token = generate_optout_token(email, send_date, secret)
    params = urllib.parse.urlencode({"email": email, "date": send_date, "token": token})
    return f"{base_url.rstrip('/')}/tracking-optout?{params}"
