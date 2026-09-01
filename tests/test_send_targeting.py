"""
Tests du ciblage des destinataires.

Propriété critique : un envoi de test ne doit jamais pouvoir retomber
silencieusement sur la liste complète des abonnés.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.gmail_tool import resolve_recipients

SUBSCRIBERS = ["a@example.com", "b@example.com", "c@example.com"]


def test_an_override_replaces_the_subscriber_list():
    assert resolve_recipients(["test@example.com"], SUBSCRIBERS) == ["test@example.com"]


def test_no_override_falls_back_to_the_subscriber_list():
    assert resolve_recipients(None, SUBSCRIBERS) == SUBSCRIBERS


def test_an_empty_override_is_refused_rather_than_falling_back():
    """Un override vide est un bug d'appel — il ne doit pas arroser les 25 abonnés."""
    with pytest.raises(ValueError, match="vide"):
        resolve_recipients([], SUBSCRIBERS)


def test_an_override_of_blank_strings_is_refused():
    with pytest.raises(ValueError, match="vide"):
        resolve_recipients(["", "   "], SUBSCRIBERS)


def test_an_override_is_normalised():
    assert resolve_recipients(["  Test@Example.COM "], SUBSCRIBERS) == ["test@example.com"]


def test_missing_subscribers_and_no_override_is_refused():
    with pytest.raises(ValueError, match="Aucun destinataire"):
        resolve_recipients(None, [])
