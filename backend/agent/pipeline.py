"""Deterministic data-science pipeline (Phase 1 + 2 of the hybrid agent).

Gathers/persists market data and computes the authoritative BUY/HOLD/SELL decision.
No LLM involved here — the result is a pure function of the data, hence reproducible.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal

from agent.data_science import (
    compute_ensemble, calculate_technical_indicators, run_arima_forecast, EnsembleDecision,
)
from agent.sentiment import score_sentiment_llm
from models import Position, Transaction
from services.market_data import (
    fetch_and_store_prices,
    fetch_and_store_fundamentals,
    fetch_and_store_news,
    prices_to_dicts,
)


def _fundamentals_to_dict(obj) -> dict | None:
    if obj is None:
        return None
    return {
        "pe_ratio": float(obj.pe_ratio) if obj.pe_ratio is not None else None,
        "revenue_growth": float(obj.revenue_growth) if obj.revenue_growth is not None else None,
        "market_cap": float(obj.market_cap) if obj.market_cap is not None else None,
        "eps": float(obj.eps) if obj.eps is not None else None,
        "beta": float(obj.beta) if obj.beta is not None else None,
        "fifty_two_week_high": float(obj.fifty_two_week_high) if obj.fifty_two_week_high is not None else None,
        "fifty_two_week_low": float(obj.fifty_two_week_low) if obj.fifty_two_week_low is not None else None,
    }


async def gather_market_data(ticker: str, db: AsyncSession, force: bool = False):
    """Phase 1: ensure prices, fundamentals and news are fetched + persisted."""
    ticker = ticker.upper()
    rows = await fetch_and_store_prices(ticker, db, period="2y", force=force)
    prices = prices_to_dicts(rows)
    fundamentals = _fundamentals_to_dict(await fetch_and_store_fundamentals(ticker, db, force=force))
    news = await fetch_and_store_news(ticker, db, days=14, force=force)

    # Prefer an LLM aggregate sentiment; fall back to the stored keyword average.
    news_sentiment = None
    if news:
        news_sentiment = await score_sentiment_llm([n.headline for n in news])
        if news_sentiment is None:
            news_sentiment = sum(float(n.sentiment or 0) for n in news) / len(news)
    return prices, fundamentals, news_sentiment, news


async def compute_portfolio_context(ticker: str, db: AsyncSession, current_prices: dict[str, float]) -> dict | None:
    """Position context for a ticker: avg buy price, unrealized P&L %, weight in the whole portfolio."""
    ticker = ticker.upper()
    pos = (await db.execute(select(Position).where(Position.ticker == ticker))).scalar_one_or_none()
    if not pos:
        return None

    buys = (
        await db.execute(
            select(Transaction).where(Transaction.ticker == ticker, Transaction.type == "buy")
        )
    ).scalars().all()
    if buys:
        total_cost = sum(float(t.shares) * float(t.price) for t in buys)
        total_shares = sum(float(t.shares) for t in buys)
        avg_buy = total_cost / total_shares if total_shares > 0 else None
    else:
        avg_buy = float(pos.manual_buy_price) if pos.manual_buy_price else None

    current = current_prices.get(ticker)
    pnl_pct = ((current - avg_buy) / avg_buy * 100) if (avg_buy and current) else None

    # Weight across ALL positions
    all_positions = (await db.execute(select(Position))).scalars().all()
    total_value = sum(current_prices.get(p.ticker, 0) * float(p.shares) for p in all_positions)
    position_value = (current or 0) * float(pos.shares)
    weight = (position_value / total_value * 100) if total_value > 0 else None

    return {
        "name": pos.name,
        "sector": pos.sector,
        "shares": float(pos.shares),
        "avg_buy_price": round(avg_buy, 4) if avg_buy else None,
        "current_price": current,
        "unrealized_pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "portfolio_weight": round(weight, 2) if weight is not None else None,
    }


async def _snapshot_row(ticker: str, name: str, sector: str, shares: float,
                        current_prices: dict[str, float], total_value: float) -> dict:
    """Enrich one position (own DB session) — runs concurrently with the others."""
    async with AsyncSessionLocal() as db:
        price_rows = await fetch_and_store_prices(ticker, db)  # cached
        prices = prices_to_dicts(price_rows)
        ind = calculate_technical_indicators(prices)
        ctx = await compute_portfolio_context(ticker, db, current_prices)
        fund = await fetch_and_store_fundamentals(ticker, db)  # cached
        news = await fetch_and_store_news(ticker, db, days=14)  # cached
    # ARIMA is CPU-bound — off the event loop so the positions' forecasts overlap.
    arima = await asyncio.to_thread(run_arima_forecast, prices)

    cur = current_prices.get(ticker)
    news_sentiment = round(sum(float(n.sentiment or 0) for n in news) / len(news), 2) if news else None
    forecast_pct = (
        round((arima.forecast_30d - cur) / cur * 100, 1) if arima.forecast_30d and cur else None
    )
    value = (cur or 0) * shares
    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "shares": shares,
        "current_price": cur,
        "avg_buy_price": ctx.get("avg_buy_price") if ctx else None,
        "pnl_pct": ctx.get("unrealized_pnl_pct") if ctx else None,
        "weight_pct": round(value / total_value * 100, 1) if total_value > 0 else None,
        "rsi": round(ind.rsi_14, 1) if ind.rsi_14 is not None else None,
        "trend": ind.trend_signal,
        "dividend_yield": float(fund.dividend_yield) if fund and fund.dividend_yield is not None else None,
        "pe_ratio": float(fund.pe_ratio) if fund and fund.pe_ratio is not None else None,
        "beta": float(fund.beta) if fund and fund.beta is not None else None,
        "news_sentiment": news_sentiment,
        "recent_headlines": [n.headline for n in news[:3]],
        "arima_forecast_30d_pct": forecast_pct,
    }


async def build_portfolio_snapshot(db: AsyncSession, current_prices: dict[str, float]) -> dict:
    """Compact, LLM-friendly overview of the whole portfolio (prices, indicators, fundamentals,
    news sentiment + headlines, ARIMA 30-day forecast). Positions are enriched concurrently to
    keep latency low enough for interactive chat/rebalancing."""
    positions = (await db.execute(select(Position))).scalars().all()
    total_value = sum(current_prices.get(p.ticker, 0) * float(p.shares) for p in positions)

    rows_out = await asyncio.gather(*[
        _snapshot_row(p.ticker, p.name, p.sector, float(p.shares), current_prices, total_value)
        for p in positions
    ])

    sector_value: dict[str, float] = {}
    for r in rows_out:
        sector_value[r["sector"]] = sector_value.get(r["sector"], 0) + (r["current_price"] or 0) * r["shares"]
    sector_weights = {
        s: round(v / total_value * 100, 1) for s, v in sector_value.items()
    } if total_value > 0 else {}

    return {
        "total_value": round(total_value, 2),
        "currency": "USD",
        "position_count": len(positions),
        "sector_weights_pct": sector_weights,
        "positions": list(rows_out),
    }


async def build_ensemble_decision(
    ticker: str, db: AsyncSession, current_prices: dict[str, float], force: bool = False
) -> tuple[EnsembleDecision, dict]:
    """Phase 1 + 2: gather data, then compute the deterministic decision."""
    prices, fundamentals, news_sentiment, _news = await gather_market_data(ticker, db, force=force)
    portfolio_ctx = await compute_portfolio_context(ticker, db, current_prices)
    decision = compute_ensemble(prices, fundamentals, news_sentiment, portfolio_ctx)

    # Indicators are based on the last stored daily close; prefer the LIVE intraday price
    # for what the LLM reports as "current price" (the close can be days old).
    live_price = current_prices.get(ticker.upper())
    if live_price and decision.technicals:
        decision.technicals["current_price"] = round(float(live_price), 2)
        decision.technicals["current_price_hinweis"] = "Live-Kurs; SMA/Bollinger/RSI/MACD basieren auf dem letzten Tagesschluss"

    context = {
        "fundamentals": fundamentals,
        "technicals": decision.technicals,
        "news_sentiment": news_sentiment,
        "portfolio": portfolio_ctx,
        "price_points": len(prices),
        "has_price_data": len(prices) > 0,
    }
    return decision, context
