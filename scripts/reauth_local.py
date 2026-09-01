"""
reauth_local.py — Renouvelle le token Gmail OAuth en local.

À lancer après une erreur "Gmail token expired — invalid_grant" lors d'une
exécution locale. Ouvre le navigateur pour re-authentifier via Google OAuth
et sauvegarde le nouveau token sur disque.

Usage:
    venv/bin/python scripts/reauth_local.py
"""

import sys
from pathlib import Path

# Permettre l'import depuis la racine du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(override=True)

from config import config
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def reauth_local() -> None:
    token_path = Path(config.GMAIL_TOKEN_PATH)
    credentials_path = Path(config.GMAIL_CREDENTIALS_PATH)

    if not credentials_path.exists():
        print(f"[ERREUR] credentials.json introuvable : {credentials_path}")
        print("  Télécharger depuis Google Cloud Console → APIs & Services → Credentials")
        print("  Sauvegarder sous le chemin défini par GMAIL_CREDENTIALS_PATH dans .env")
        sys.exit(1)

    # Supprimer l'ancien token expiré/révoqué
    if token_path.exists():
        token_path.unlink()
        print(f"Ancien token supprimé : {token_path}")

    print("Ouverture du navigateur pour l'authentification Google…")
    print("(Si le navigateur ne s'ouvre pas automatiquement, copier l'URL affichée dans le terminal)")

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())

    print(f"\nToken sauvegardé : {token_path}")
    print("Vous pouvez maintenant relancer main.py normalement.")


if __name__ == "__main__":
    reauth_local()
