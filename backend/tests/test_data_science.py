"""Tests for the deterministic data-science core (technicals, ARIMA, RandomForest, ensemble).

These are pure functions of their inputs (random_state is fixed), so the suite asserts both
behaviour on synthetic series and exact reproducibility — no network, no DB, no LLM.
"""
import math
from datetime import date, timedelta

from agent.data_science import (
    calculate_technical_indicators,
    run_arima_forecast,
    run_ml_signal,
    compute_ensemble,
)


def _series(closes: list[float]) -> list[dict]:
    """Build OHLCV dicts (one bar per day) from a list of closing prices."""
    start = date(2023, 1, 1)
    return [
        {"date": str(start + timedelta(days=i)), "open": c, "high": c, "low": c, "close": c, "volume": 1000}
        for i, c in enumerate(closes)
    ]


# A small deterministic oscillation is added to the drift so the series has both up- and
# down-days. A strictly monotonic series has an undefined RSI (no losses → division by zero),
# which is a real edge case but not what these "normal market data" tests intend to exercise.
def _uptrend(n: int, start: float = 50.0, step: float = 0.5) -> list[dict]:
    return _series([start + i * step + 2.0 * math.sin(i / 2.0) for i in range(n)])


def _downtrend(n: int, start: float = 200.0, step: float = 0.5) -> list[dict]:
    return _series([start - i * step + 2.0 * math.sin(i / 2.0) for i in range(n)])


# ── Technical indicators ────────────────────────────────────────────────────────

def test_technicals_too_few_points_returns_neutral_none():
    ind = calculate_technical_indicators(_series([100.0] * 10))
    assert ind.trend_signal == "NEUTRAL"
    assert ind.rsi_14 is None and ind.sma_20 is None and ind.current_price is None


def test_technicals_constant_prices_do_not_crash():
    # Constant series → RSI denominator is zero (NaN); must be handled, not raised.
    ind = calculate_technical_indicators(_series([100.0] * 40))
    assert ind.current_price == 100.0
    assert ind.rsi_14 is None  # undefined on a flat series
    assert ind.trend_signal in {"BULLISH", "BEARISH", "NEUTRAL"}


def test_technicals_uptrend_is_populated():
    ind = calculate_technical_indicators(_uptrend(60))
    assert ind.current_price is not None
    assert ind.sma_20 is not None
    assert ind.trend_signal in {"BULLISH", "BEARISH", "NEUTRAL"}


# ── ARIMA ─────────────────────────────────────────────────────────────────────

def test_arima_too_few_points_holds():
    fc = run_arima_forecast(_uptrend(59))
    assert fc.signal == "HOLD"
    assert fc.forecast_30d is None and fc.confidence is None
    assert "60" in fc.details


def test_arima_fits_on_enough_points():
    fc = run_arima_forecast(_uptrend(160))
    assert fc.signal in {"BUY", "HOLD", "SELL"}
    assert fc.forecast_7d is not None and fc.forecast_30d is not None
    assert 0.0 <= fc.confidence <= 1.0


def test_arima_is_deterministic():
    s = _uptrend(160)
    a, b = run_arima_forecast(s), run_arima_forecast(s)
    assert (a.signal, a.forecast_30d, a.confidence) == (b.signal, b.forecast_30d, b.confidence)


# ── RandomForest ───────────────────────────────────────────────────────────────

def test_ml_too_few_points_holds():
    fc = run_ml_signal(_uptrend(99))
    assert fc.signal == "HOLD"
    assert fc.confidence is None and "100" in fc.details


def test_ml_signal_is_valid_and_deterministic():
    # The trailing bars default to HOLD (their future label is unknown), so the predicted
    # direction is model-dependent — assert the contract (valid signal + confidence) and,
    # crucially, reproducibility (random_state=42), not a hard-coded direction.
    s = _uptrend(160)
    a = run_ml_signal(s)
    b = run_ml_signal(s)
    assert a.signal in {"BUY", "HOLD", "SELL"}
    assert 0.0 <= a.confidence <= 1.0
    assert (a.signal, a.confidence, a.details) == (b.signal, b.confidence, b.details)


def test_ml_signal_runs_on_downtrend():
    fc = run_ml_signal(_downtrend(160))
    assert fc.signal in {"BUY", "HOLD", "SELL"}
    assert 0.0 <= fc.confidence <= 1.0


# ── Ensemble ───────────────────────────────────────────────────────────────────

def test_ensemble_is_pure_function():
    s = _uptrend(160)
    fund = {"revenue_growth": 0.2, "pe_ratio": 18}
    a = compute_ensemble(s, fundamentals=fund, news_sentiment=0.3)
    b = compute_ensemble(s, fundamentals=fund, news_sentiment=0.3)
    assert (a.signal, a.score, a.confidence) == (b.signal, b.score, b.confidence)
    assert a.components == b.components


def test_ensemble_empty_prices_is_hold_score_zero():
    dec = compute_ensemble([])
    assert dec.signal == "HOLD"
    assert dec.score == 0.0
    assert -1.0 <= dec.score <= 1.0 and 0.05 <= dec.confidence <= 0.95


def test_ensemble_news_sentiment_is_clamped():
    high = compute_ensemble([], news_sentiment=5.0)
    low = compute_ensemble([], news_sentiment=-5.0)
    assert high.components["news"]["value"] == 1.0
    assert low.components["news"]["value"] == -1.0


def test_ensemble_portfolio_rule_take_profit_and_buy_dip():
    take_profit = compute_ensemble([], portfolio_ctx={"unrealized_pnl_pct": 25})
    buy_dip = compute_ensemble([], portfolio_ctx={"unrealized_pnl_pct": -20})
    assert take_profit.components["portfolio_rule"]["contribution"] == -0.15
    assert buy_dip.components["portfolio_rule"]["contribution"] == 0.15
