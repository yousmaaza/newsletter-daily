"""
Tests de la construction du message d'envoi de test.

L'envoi de test passe par SMTP + GMAIL_APP_PASSWORD (comme auth_notifier.py)
plutôt que par OAuth : un test ne doit pas dépendre de la chaîne d'auth complète.
"""

import sys
from email import message_from_string
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.gmail_tool import build_mime_message


def test_message_carries_subject_sender_and_recipient():
    raw = build_mime_message(
        subject="[TEST] Le Brief",
        sender="expediteur@example.com",
        from_name="Daily News",
        recipient="lecteur@example.com",
        html="<p>Bonjour</p>",
    ).as_string()

    from email.header import decode_header, make_header

    parsed = message_from_string(raw)
    assert parsed["To"] == "lecteur@example.com"
    assert "expediteur@example.com" in parsed["From"]
    assert "Daily News" in str(make_header(decode_header(parsed["From"])))
    assert "Le Brief" in str(make_header(decode_header(parsed["Subject"])))


def test_message_body_is_html():
    msg = build_mime_message(
        subject="Sujet",
        sender="a@example.com",
        from_name="N",
        recipient="b@example.com",
        html="<p>Tornade dans l'Aude</p>",
    )

    payloads = [part.get_payload(decode=True) for part in msg.walk() if part.get_content_type() == "text/html"]
    assert any(b"Tornade dans l'Aude" in p for p in payloads if p)


def test_accented_subject_survives_encoding():
    raw = build_mime_message(
        subject="Le Brief du 25 août — quantique & tornade",
        sender="a@example.com",
        from_name="N",
        recipient="b@example.com",
        html="<p>x</p>",
    ).as_string()

    from email.header import decode_header, make_header
    decoded = str(make_header(decode_header(message_from_string(raw)["Subject"])))
    assert decoded == "Le Brief du 25 août — quantique & tornade"
