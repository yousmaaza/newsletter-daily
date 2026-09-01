"""
Tests du rejet des anciens identifiants réversibles à l'enregistrement.

Constaté après la migration : un hash SHA-256 non salé, ré-identifiable, est
réapparu dans data/opens_2026-08-25.csv le 26 août à 13:49 — donc APRÈS la
migration qui devait tous les supprimer.

Cause : les éditions déjà distribuées portent, dans leurs URL de pixel et de
clic, l'ancien identifiant. Elles restent dans les boîtes des lecteurs pendant
des mois. Chaque ouverture d'une ancienne édition réintroduit une donnée
ré-identifiable — la migration ne pouvait pas fermer ce robinet.

Les identifiants opaques font 32 caractères (secrets.token_hex(16)), les
anciens hashs en font 64 : la distinction est nette et sans ambiguïté.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "auth_server"))

from auth_server.identifiers import is_legacy_identifier, normalise_identifier

OPAQUE = "a3f1" * 8          # 32 hex — format actuel
LEGACY = "b7c2" * 16         # 64 hex — ancien SHA-256


def test_a_legacy_sha256_is_recognised():
    assert is_legacy_identifier(LEGACY)


def test_an_opaque_identifier_is_not_flagged():
    assert not is_legacy_identifier(OPAQUE)


def test_an_orphan_marker_is_not_flagged():
    assert not is_legacy_identifier("orphan-3")


def test_an_archived_marker_is_not_flagged():
    assert not is_legacy_identifier("archived")


def test_an_empty_value_is_not_flagged():
    assert not is_legacy_identifier("")


def test_a_sixty_four_char_non_hex_is_not_flagged():
    assert not is_legacy_identifier("z" * 64)


# ── Normalisation à l'enregistrement ─────────────────────────────────────────

def test_a_legacy_identifier_is_replaced_at_recording():
    """La ligne est conservée — les volumes restent justes — mais anonyme."""
    assert normalise_identifier(LEGACY) == "legacy"


def test_an_opaque_identifier_passes_through():
    assert normalise_identifier(OPAQUE) == OPAQUE


def test_the_case_does_not_matter():
    assert normalise_identifier(LEGACY.upper()) == "legacy"


def test_surrounding_whitespace_is_ignored():
    assert normalise_identifier(f"  {LEGACY}  ") == "legacy"


def test_a_marker_passes_through():
    assert normalise_identifier("orphan-2") == "orphan-2"
