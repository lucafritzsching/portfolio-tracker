"""Walk-forward backtest of the deterministic ensemble signal."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.data_science import compute_ensemble
from models import Position
from services.market_data import fetch_and_store_prices, prices_to_dicts


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
    agg: dict[str, dict] = {"BUY": {"n": 0, "returns": []}, "HOLD": {"n": 0, "returns": []}, "SELL": {"n": 0, "returns": []}}

    for ticker in tickers:
        ticker = ticker.upper()
        rows = await fetch_and_store_prices(ticker, db, period="2y")
        prices = prices_to_dicts(rows)
        if len(prices) < min_history + horizon_days:
            per_ticker[ticker] = {"error": f"Zu wenig Historie ({len(prices)} Tage)"}
            continue

        stats = {"BUY": [], "HOLD": [], "SELL": []}
        i = min_history
        while i + horizon_days < len(prices):
            window = prices[: i + 1]
            decision = compute_ensemble(window, fundamentals=None, news_sentiment=None, portfolio_ctx=None)
            entry = float(window[-1]["close"])
            exit_ = float(prices[i + horizon_days]["close"])
            ret_pct = (exit_ - entry) / entry * 100
            stats[decision.signal].append(ret_pct)
            i += step_days

        ticker_stats = {}
        for sig, rets in stats.items():
            if not rets:
                ticker_stats[sig] = {"n": 0, "avg_return_pct": None, "hit_rate": None}
                continue
            hits = sum(1 for r in rets if (sig == "BUY" and r > 0) or (sig == "SELL" and r < 0) or (sig == "HOLD" and abs(r) < 5))
            ticker_stats[sig] = {
                "n": len(rets),
                "avg_return_pct": round(sum(rets) / len(rets), 2),
                "hit_rate": round(hits / len(rets), 2),
            }
            agg[sig]["n"] += len(rets)
            agg[sig]["returns"].extend(rets)
        per_ticker[ticker] = ticker_stats

    aggregate = {}
    for sig, data in agg.items():
        rets = data["returns"]
        if not rets:
            aggregate[sig] = {"n": 0, "avg_return_pct": None, "hit_rate": None}
            continue
        hits = sum(1 for r in rets if (sig == "BUY" and r > 0) or (sig == "SELL" and r < 0) or (sig == "HOLD" and abs(r) < 5))
        aggregate[sig] = {
            "n": len(rets),
            "avg_return_pct": round(sum(rets) / len(rets), 2),
            "hit_rate": round(hits / len(rets), 2),
        }

    return {
        "params": {"horizon_days": horizon_days, "step_days": step_days, "min_history": min_history},
        "per_ticker": per_ticker,
        "aggregate": aggregate,
    }
