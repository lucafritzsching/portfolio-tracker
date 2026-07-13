"""Walk-forward backtest of the deterministic ensemble signal."""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.data_science import compute_ensemble
from models import Position
from services.market_data import fetch_and_store_prices, prices_to_dicts

SIGNALS = ("BUY", "HOLD", "SELL")


def _hit(sig: str, ret_pct: float) -> bool:
    if sig == "SELL":
        return ret_pct < 0
    if sig == "HOLD":
        return abs(ret_pct) < 5
    return ret_pct > 0  # BUY und baseline: positiver Forward-Return


def _summarize(sig: str, rets: list[float]) -> dict:
    if not rets:
        return {"n": 0, "avg_return_pct": None, "hit_rate": None}
    hits = sum(1 for r in rets if _hit(sig, r))
    return {
        "n": len(rets),
        "avg_return_pct": round(sum(rets) / len(rets), 2),
        "hit_rate": round(hits / len(rets), 2),
    }


def backtest_prices(
    prices: list[dict],
    horizon_days: int = 20,
    step_days: int = 5,
    min_history: int = 120,
) -> tuple[dict, dict[str, list[float]]]:
    """Pure Walk-Forward-Simulation über EINE Kursreihe (kein IO — testbar, thread-fähig).

    Liefert (stats, returns_by_sig). ``baseline`` sammelt die Forward-Renditen ALLER Fenster
    unabhängig vom Signal — das ist die Buy&Hold-Basisrate, gegen die BUY/SELL antreten müssen.
    """
    returns_by_sig: dict[str, list[float]] = {sig: [] for sig in SIGNALS} | {"baseline": []}
    i = min_history
    while i + horizon_days < len(prices):
        window = prices[: i + 1]
        decision = compute_ensemble(window, fundamentals=None, news_sentiment=None, portfolio_ctx=None)
        entry = float(window[-1]["close"])
        exit_ = float(prices[i + horizon_days]["close"])
        ret_pct = (exit_ - entry) / entry * 100
        returns_by_sig[decision.signal].append(ret_pct)
        returns_by_sig["baseline"].append(ret_pct)
        i += step_days

    stats = {sig: _summarize(sig, rets) for sig, rets in returns_by_sig.items()}
    return stats, returns_by_sig


async def run_backtest(
    db: AsyncSession,
    tickers: list[str] | None = None,
    horizon_days: int = 20,
    step_days: int = 5,
    min_history: int = 120,
) -> dict:
    """For each ticker, simulate ensemble signals on rolling windows and measure forward returns."""
    if not tickers:
        positions = (await db.execute(select(Position))).scalars().all()
        tickers = [p.ticker for p in positions]
    if not tickers:
        return {
            "params": {"horizon_days": horizon_days, "step_days": step_days, "min_history": min_history},
            "per_ticker": {},
            "aggregate": {},
        }

    per_ticker: dict = {}
    agg: dict[str, list[float]] = {sig: [] for sig in SIGNALS} | {"baseline": []}

    for ticker in tickers:
        ticker = ticker.upper()
        rows = await fetch_and_store_prices(ticker, db, period="2y")
        prices = prices_to_dicts(rows)
        if len(prices) < min_history + horizon_days:
            per_ticker[ticker] = {"error": f"Zu wenig Historie ({len(prices)} Tage)"}
            continue

        # CPU-schwer (ARIMA+RF je Fenster) → aus dem Event-Loop auslagern, damit SSE/HTTP reaktiv bleiben.
        stats, returns_by_sig = await asyncio.to_thread(
            backtest_prices, prices, horizon_days, step_days, min_history
        )
        per_ticker[ticker] = stats
        for sig, rets in returns_by_sig.items():
            agg[sig].extend(rets)

    aggregate = {sig: _summarize(sig, rets) for sig, rets in agg.items()}

    return {
        "params": {"horizon_days": horizon_days, "step_days": step_days, "min_history": min_history},
        "per_ticker": per_ticker,
        "aggregate": aggregate,
    }
