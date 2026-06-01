"""Deterministic data-science pipeline (Phase 1 + 2 of the hybrid agent).

Gathers/persists market data and computes the authoritative BUY/HOLD/SELL decision.
No LLM involved here — the result is a pure function of the data, hence reproducible.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.data_science import compute_ensemble, EnsembleDecision
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


async def build_ensemble_decision(
    ticker: str, db: AsyncSession, current_prices: dict[str, float], force: bool = False
) -> tuple[EnsembleDecision, dict]:
    """Phase 1 + 2: gather data, then compute the deterministic decision."""
    prices, fundamentals, news_sentiment, _news = await gather_market_data(ticker, db, force=force)
    portfolio_ctx = await compute_portfolio_context(ticker, db, current_prices)
    decision = compute_ensemble(prices, fundamentals, news_sentiment, portfolio_ctx)
    context = {
        "fundamentals": fundamentals,
        "news_sentiment": news_sentiment,
        "portfolio": portfolio_ctx,
        "price_points": len(prices),
    }
    return decision, context
