"""
Tests des chiffres affichés dans le bloc transparence.

Ces chiffres partent chez les lecteurs : ils doivent être exacts, et le calcul
doit rester correct quand un mois est vide ou quand l'historique est court.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.newsletter_stats import compute_transparency_stats


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path) -> Path:
    """Deux mois : juillet (2 éditions, 3 clics), août (2 éditions, 8 clics)."""
    d = tmp_path / "data"
    d.mkdir()
    opens_header = '"timestamp","email_hash","send_date"'
    clicks_header = '"timestamp","email_hash","send_date","article_rank","url"'

    for day, hashes in [
        ("2026-07-01", ["aaa", "bbb"]),
        ("2026-07-02", ["aaa"]),
        ("2026-08-01", ["aaa", "bbb", "ccc"]),
        ("2026-08-02", ["bbb", "ccc"]),
    ]:
        _write_csv(d / f"opens_{day}.csv", opens_header,
                   [f'"{day}T06:00:00Z","{h}","{day}"' for h in hashes])

    for day, n in [("2026-07-01", 2), ("2026-07-02", 1), ("2026-08-01", 5), ("2026-08-02", 3)]:
        _write_csv(d / f"clicks_{day}.csv", clicks_header,
                   [f'"{day}T07:00:00Z","aaa","{day}","1","https://x"' for _ in range(n)])
    return d


def test_total_editions_counts_every_edition_with_data(data_dir):
    stats = compute_transparency_stats(data_dir, subscriber_count=4)

    assert stats["total_editions"] == 4


def test_unique_readers_deduplicates_across_editions(data_dir):
    stats = compute_transparency_stats(data_dir, subscriber_count=4)

    assert stats["unique_readers"] == 3


def test_open_rate_is_average_openers_per_edition_over_subscribers(data_dir):
    # ouvreurs par édition : 2, 1, 3, 2 → moyenne 2,0 sur 4 abonnés → 50 %
    stats = compute_transparency_stats(data_dir, subscriber_count=4)

    assert stats["open_rate_pct"] == 50


def test_click_trend_reports_clicks_per_edition_by_month(data_dir):
    stats = compute_transparency_stats(data_dir, subscriber_count=4)
    trend = {m["month"]: m["value"] for m in stats["click_trend"]}

    assert trend["2026-07"] == 1.5   # 3 clics / 2 éditions
    assert trend["2026-08"] == 4.0   # 8 clics / 2 éditions


def test_click_trend_bars_are_scaled_to_the_tallest_month(data_dir):
    stats = compute_transparency_stats(data_dir, subscriber_count=4)
    bars = {m["month"]: m["height"] for m in stats["click_trend"]}

    assert bars["2026-08"] == 68           # le mois le plus fort occupe toute la hauteur
    assert bars["2026-07"] < bars["2026-08"]
    assert all(h >= 3 for h in bars.values())  # jamais une barre invisible


def test_months_are_ordered_chronologically(data_dir):
    stats = compute_transparency_stats(data_dir, subscriber_count=4)

    assert [m["month"] for m in stats["click_trend"]] == ["2026-07", "2026-08"]


def test_no_data_yields_zeroes_rather_than_a_crash(tmp_path):
    empty = tmp_path / "data"
    empty.mkdir()

    stats = compute_transparency_stats(empty, subscriber_count=25)

    assert stats["total_editions"] == 0
    assert stats["unique_readers"] == 0
    assert stats["open_rate_pct"] == 0
    assert stats["click_trend"] == []


def test_zero_subscribers_does_not_divide_by_zero(data_dir):
    """
    Sans liste d'abonnés, le calcul retombe sur le pic d'ouvreurs observé
    plutôt que de lever ou d'afficher un taux absurde.
    """
    stats = compute_transparency_stats(data_dir, subscriber_count=0)

    assert 0 <= stats["open_rate_pct"] <= 100
