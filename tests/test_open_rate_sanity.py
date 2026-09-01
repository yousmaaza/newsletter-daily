"""
Tests de robustesse du taux d'ouverture affiché aux lecteurs.

Constaté en CI : le bloc a affiché « 1686 % ». ci-validate.yml écrase
recipients.toml avec une seule adresse, et le taux divisait par la taille de
cette liste tronquée.

Le dénominateur ne peut jamais être plus petit que le nombre d'ouvreurs
observés sur une édition : on ne peut pas avoir plus de lecteurs que
d'abonnés. Cette contrainte suffit à rendre le calcul auto-correcteur.
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.newsletter_stats import compute_transparency_stats


def _edition(directory: Path, day: str, openers: int) -> None:
    rows = [f'"{day}T06:00:00Z","id-{i}","{day}"' for i in range(openers)]
    (directory / f"opens_{day}.csv").write_text(
        '"timestamp","email_hash","send_date"\n' + "\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    _edition(d, "2026-08-24", 12)
    _edition(d, "2026-08-25", 16)
    _edition(d, "2026-08-26", 20)      # le pic : au moins 20 abonnés existaient
    return d


def test_a_truncated_recipient_list_does_not_inflate_the_rate(data_dir):
    """Le cas CI : recipients.toml écrasé avec une seule adresse."""
    stats = compute_transparency_stats(data_dir, subscriber_count=1)

    assert stats["open_rate_pct"] <= 100


def test_the_rate_never_exceeds_one_hundred(data_dir):
    for count in (0, 1, 2, 5, 25):
        assert compute_transparency_stats(data_dir, subscriber_count=count)["open_rate_pct"] <= 100


def test_a_plausible_list_gives_the_expected_rate(data_dir):
    # ouvreurs par édition : 12, 16, 20 → moyenne 16 ; sur 25 abonnés → 64 %
    stats = compute_transparency_stats(data_dir, subscriber_count=25)

    assert stats["open_rate_pct"] == 64


def test_a_too_small_list_falls_back_on_the_observed_peak(data_dir):
    """On ne peut pas avoir 20 ouvreurs avec 5 abonnés : le pic fait foi."""
    stats = compute_transparency_stats(data_dir, subscriber_count=5)

    assert stats["open_rate_pct"] == 80      # moyenne 16 sur un pic de 20


def test_the_peak_is_ignored_when_the_list_is_larger(data_dir):
    """Un abonné qui n'ouvre jamais doit continuer de peser sur le taux."""
    stats = compute_transparency_stats(data_dir, subscriber_count=40)

    assert stats["open_rate_pct"] == 40      # moyenne 16 sur 40 abonnés


def test_no_data_still_reports_zero(tmp_path):
    empty = tmp_path / "data"
    empty.mkdir()

    assert compute_transparency_stats(empty, subscriber_count=25)["open_rate_pct"] == 0
