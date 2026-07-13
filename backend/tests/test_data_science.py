"""Tests für die DS-Ehrlichkeit: purged RF-Holdout + Mehrheits-Baseline, ARIMA-Validierung
gegen die Random-Walk-Baseline und die Buy&Hold-Baseline im Walk-Forward-Backtest.

Alles pure Funktionen über synthetische Kursreihen — kein Netz, keine DB, kein Mock nötig.
"""
from datetime import date, timedelta

import numpy as np

from agent.data_science import run_arima_forecast, run_ml_signal
from eval.backtest import backtest_prices


def _series(n: int = 400, seed: int = 42, drift: float = 0.0005) -> list[dict]:
    """Deterministische synthetische Kursreihe (Random Walk mit Drift)."""
    rng = np.random.RandomState(seed)
    close = 100 * np.cumprod(1 + drift + 0.01 * rng.randn(n))
    start = date(2024, 1, 1)
    return [
        {
            "date": str(start + timedelta(days=i)),
            "open": float(c), "high": float(c * 1.01), "low": float(c * 0.99),
            "close": float(c), "volume": 1_000_000,
        }
        for i, c in enumerate(close)
    ]


PRICES = _series()


def test_ml_signal_reports_purged_holdout_vs_majority_baseline():
    fc = run_ml_signal(PRICES)
    assert fc.signal in ("BUY", "HOLD", "SELL")
    assert fc.confidence is not None and 0.0 <= fc.confidence <= 1.0
    assert "purged" in fc.details and "Gap" in fc.details
    assert "Mehrheitsklassen-Baseline" in fc.details
    assert "class_weight=balanced" in fc.details


def test_ml_signal_excludes_unlabeled_tail_from_training():
    """Die letzten 20 Zeilen haben keine bekannte Zukunftsrendite und dürfen nicht als
    Default-HOLD ins Training rutschen: gelabelte Punkte < Feature-Zeilen."""
    fc = run_ml_signal(PRICES)
    # details nennt die Zahl der gelabelten Punkte; bei 400 Bars mit ~50 Warmup-Zeilen
    # und 20 ungelabelten Zeilen am Ende muss sie klar unter 380 liegen.
    n_labeled = int(fc.details.split(" gelabelte")[0].split(", ")[-1])
    assert n_labeled <= len(PRICES) - 20 - 49  # Warmup (SMA50) + Label-Horizont fehlen


def test_arima_validate_appends_baseline_comparison():
    with_val = run_arima_forecast(PRICES, validate=True)
    without = run_arima_forecast(PRICES)
    assert "Random-Walk-Baseline" in with_val.details and "MAE" in with_val.details
    assert "Random-Walk-Baseline" not in without.details
    # Die eigentliche Prognose bleibt identisch — die Validierung ist nur ein Anhang.
    assert with_val.forecast_30d == without.forecast_30d
    assert with_val.signal == without.signal


def test_backtest_prices_baseline_covers_all_windows():
    prices = _series(n=400, seed=7)
    stats, returns_by_sig = backtest_prices(prices, horizon_days=20, step_days=40, min_history=300)
    # Fenster bei i = 300, 340, 380? → i + 20 < 400 ⇒ i ∈ {300, 340} = 2 Fenster.
    n_signals = sum(stats[s]["n"] for s in ("BUY", "HOLD", "SELL"))
    assert stats["baseline"]["n"] == n_signals == 2
    # Baseline-Durchschnitt = Handrechnung über die Forward-Renditen aller Fenster.
    expected = []
    for i in (300, 340):
        entry = prices[i]["close"]
        exit_ = prices[i + 20]["close"]
        expected.append((exit_ - entry) / entry * 100)
    assert stats["baseline"]["avg_return_pct"] == round(sum(expected) / len(expected), 2)
    # hit_rate der Baseline = Anteil positiver Fenster.
    assert stats["baseline"]["hit_rate"] == round(sum(1 for r in expected if r > 0) / len(expected), 2)


def test_backtest_prices_no_windows_returns_empty_stats():
    stats, _ = backtest_prices(_series(n=100), horizon_days=20, step_days=5, min_history=120)
    assert stats["baseline"]["n"] == 0 and stats["baseline"]["avg_return_pct"] is None
