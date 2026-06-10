"""Tests für die reinen Backtest-Rechenteile (Alt-B Phase 3)."""
from services.backtest import BacktestEvent, group_alphas, has_edge, pct, summarize


def test_pct():
    assert pct(100, 110) == 10.0
    assert pct(100, 90) == -10.0
    assert pct(0, 50) == 0.0


def test_summarize_empty():
    s = summarize([])
    assert s["n"] == 0 and s["median"] is None


def test_summarize_values():
    s = summarize([2.0, -1.0, 4.0, 6.0])  # 3 von 4 positiv
    assert s["n"] == 4
    assert s["median"] == 3.0
    assert s["win_rate"] == 75


def _ev(setup, insider, strength, alpha):
    return BacktestEvent("ABC", "2025-01-01", setup, insider, strength, alpha)


def test_group_alphas_buckets():
    events = [
        _ev(True,  True,  5, 10.0),   # Voll Alt-B
        _ev(True,  False, 4,  2.0),   # Setup + Kat>=4 (kein Insider)
        _ev(False, False, 3, -3.0),   # Kat>=3 ohne Setup
        _ev(True,  False, 0, -1.0),   # Setup allein (kein Katalysator)
        _ev(False, False, 0,  5.0),   # Baseline
    ]
    g = group_alphas(events)
    assert g["Baseline (Zufallseinstieg)"] == [5.0]
    assert g["Katalysator >= 3"] == [10.0, 2.0, -3.0]
    assert g["Katalysator >= 4 (stark)"] == [10.0, 2.0]
    assert g["Setup allein"] == [-1.0]
    assert g["Setup + Katalysator >= 3"] == [10.0, 2.0]
    assert g["VOLL Alt-B (Setup+Kat+Insider)"] == [10.0]


def test_has_edge_rule():
    assert has_edge({"n": 40, "median": 3.0, "win_rate": 60})
    assert not has_edge({"n": 40, "median": 1.0, "win_rate": 60})   # Median zu niedrig
    assert not has_edge({"n": 10, "median": 5.0, "win_rate": 70})   # N zu klein
    assert not has_edge({"n": 40, "median": 3.0, "win_rate": 45})   # Trefferquote <= 50
