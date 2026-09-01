"""
check_apis.py — Vérifie que les APIs dont dépend l'envoi quotidien répondent.

Trois dépendances, dans l'ordre du pipeline : Anthropic rédige, Brave cherche
les articles, Gmail expédie. Si l'une des trois est muette, l'édition du matin
ne part pas — autant le savoir avant 8h que dans les logs de la CI.

Usage:
    python scripts/check_apis.py
"""

import os
import sys
from pathlib import Path

# Permettre l'import depuis la racine du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from dotenv import load_dotenv

load_dotenv(override=True)


def check_anthropic(api_key: str | None) -> bool:
    print("Anthropic — rédaction de la newsletter")
    if not api_key:
        print("  ❌ MANQUANT — définir ANTHROPIC_API_KEY dans .env")
        return False
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "ping"}],
            },
            timeout=20,
        )
        if r.ok:
            print("  ✅ OK — la clé répond")
            return True
        if r.status_code == 401:
            print("  ❌ CLÉ REFUSÉE — en générer une sur https://console.anthropic.com")
        elif r.status_code == 429:
            print("  ⚠️  RATE LIMIT — la clé est valide mais saturée")
        else:
            print(f"  ❌ HTTP {r.status_code} — {r.text[:150]}")
        return False
    except Exception as e:
        print(f"  ⚠️  ERREUR — {e}")
        return False


def check_brave(api_key: str | None) -> bool:
    print("\nBrave Search — recherche des articles")
    if not api_key:
        print("  ❌ MANQUANT — définir BRAVE_API_KEY dans .env")
        return False
    try:
        r = requests.get(
            "https://api.search.brave.com/res/v1/news/search",
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            params={"q": "actualité", "count": 1, "country": "fr"},
            timeout=20,
        )
        if r.ok:
            count = len(r.json().get("results", []))
            print(f"  ✅ OK — {count} résultat(s) reçu(s)")
            return True
        if r.status_code in (401, 403):
            print("  ❌ CLÉ REFUSÉE — vérifier l'abonnement sur https://brave.com/search/api/")
        elif r.status_code == 429:
            print("  ⚠️  QUOTA ÉPUISÉ — le plan gratuit est limité par mois")
        else:
            print(f"  ❌ HTTP {r.status_code} — {r.text[:150]}")
        return False
    except Exception as e:
        print(f"  ⚠️  ERREUR — {e}")
        return False


def check_gmail() -> bool:
    """
    Vérifie le jeton OAuth local, celui-là même qu'utilise l'envoi réel.
    C'est la panne la plus fréquente en local : le re-auth déclenché depuis
    auth_server met à jour le secret GitHub, jamais ~/.gmail-mcp/token.json.
    """
    print("\nGmail — expédition")
    token_path = Path(os.path.expanduser(
        os.getenv("GMAIL_TOKEN_PATH", "~/.gmail-mcp/token.json")))
    if not token_path.exists():
        print(f"  ❌ JETON ABSENT — {token_path}")
        print("     Le générer : venv/bin/python scripts/reauth_local.py")
        return False
    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(token_path))
        if creds.valid:
            print("  ✅ OK — jeton valide")
            return True
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                print("  ✅ OK — jeton expiré mais rafraîchi avec succès")
                return True
            except RefreshError:
                print("  ❌ JETON RÉVOQUÉ (invalid_grant) — le refresh échoue")
                print("     Le régénérer : venv/bin/python scripts/reauth_local.py")
                return False
        print("  ❌ JETON INVALIDE et non rafraîchissable")
        print("     Le régénérer : venv/bin/python scripts/reauth_local.py")
        return False
    except Exception as e:
        print(f"  ⚠️  ERREUR — {e}")
        return False


def check_recipients() -> bool:
    """Un pipeline vert qui n'envoie à personne reste un pipeline inutile."""
    print("\nDestinataires")
    try:
        from config import config

        count = len(config.GMAIL_TO)
    except Exception as e:
        print(f"  ⚠️  ERREUR de configuration — {e}")
        return False
    if not count:
        print("  ❌ AUCUN destinataire — vérifier config/recipients.toml ou GMAIL_TO")
        return False
    if not Path("config/recipients.toml").exists():
        print(f"  ⚠️  {count} destinataire(s), mais depuis GMAIL_TO — recipients.toml absent")
        print("     Rapatrier la vraie liste : venv/bin/python scripts/fetch_subscriber_data.py")
        return False
    print(f"  ✅ OK — {count} destinataire(s)")
    return True


if __name__ == "__main__":
    print("=" * 55)
    print("Vérification des APIs de l'envoi quotidien")
    print("=" * 55)

    checks = [
        check_anthropic(os.getenv("ANTHROPIC_API_KEY")),
        check_brave(os.getenv("BRAVE_API_KEY")),
        check_gmail(),
        check_recipients(),
    ]

    print()
    print("=" * 55)
    if all(checks):
        print("✅ Tout est vert — l'édition du matin peut partir")
        sys.exit(0)
    print(f"❌ {checks.count(False)}/{len(checks)} vérification(s) en échec")
    sys.exit(1)
