from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Position
from schemas import PriceHistoryOut, FundamentalsOut, NewsItemOut
from services.market_data import (
    fetch_and_store_prices,
    fetch_and_store_fundamentals,
    fetch_and_store_news,
)

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/history/{ticker}", response_model=list[PriceHistoryOut])
async def get_price_history(
    ticker: str,
    period: str = Query("1y", description="1mo, 3mo, 6mo, 1y, 2y, 5y"),
    db: AsyncSession = Depends(get_db),
):
    rows = await fetch_and_store_prices(ticker, db, period=period)
    if not rows:
        raise HTTPException(404, f"Keine Kursdaten für {ticker.upper()} gefunden")
    return rows


@router.get("/fundamentals/{ticker}", response_model=FundamentalsOut)
async def get_fundamentals(ticker: str, db: AsyncSession = Depends(get_db)):
    obj = await fetch_and_store_fundamentals(ticker, db)
    if obj is None:
        raise HTTPException(404, f"Keine Fundamentaldaten für {ticker.upper()}")
    return FundamentalsOut(
        ticker=obj.ticker,
        pe_ratio=float(obj.pe_ratio) if obj.pe_ratio is not None else None,
        market_cap=float(obj.market_cap) if obj.market_cap is not None else None,
        eps=float(obj.eps) if obj.eps is not None else None,
        revenue_growth=float(obj.revenue_growth) if obj.revenue_growth is not None else None,
        fifty_two_week_high=float(obj.fifty_two_week_high) if obj.fifty_two_week_high is not None else None,
        fifty_two_week_low=float(obj.fifty_two_week_low) if obj.fifty_two_week_low is not None else None,
        dividend_yield=float(obj.dividend_yield) if obj.dividend_yield is not None else None,
        beta=float(obj.beta) if obj.beta is not None else None,
        fetched_at=obj.fetched_at,
    )


@router.post("/warmup")
async def warmup(db: AsyncSession = Depends(get_db)):
    """Pre-fetch + cache prices/fundamentals/news for all portfolio tickers (run before a demo).

    Forces a refresh so the DB is current and the live demo no longer depends on yfinance/Finnhub.
    """
    tickers = (await db.execute(select(Position.ticker))).scalars().all()
    results = {}
    for ticker in tickers:
        try:
            prices = await fetch_and_store_prices(ticker, db, period="2y", force=True)
            await fetch_and_store_fundamentals(ticker, db, force=True)
            news = await fetch_and_store_news(ticker, db, days=14, force=True)
            results[ticker] = {"price_points": len(prices), "news_items": len(news)}
        except Exception as e:
            results[ticker] = {"error": str(e)}
    return {"warmed_up": len(tickers), "details": results}


@router.get("/news/{ticker}", response_model=list[NewsItemOut])
async def get_news(ticker: str, days: int = Query(7, le=30), db: AsyncSession = Depends(get_db)):
    news = await fetch_and_store_news(ticker, db, days=days)
    return [
        NewsItemOut(
            id=n.id, ticker=n.ticker, headline=n.headline, summary=n.summary,
            url=n.url, source=n.source, published_at=n.published_at,
            sentiment=float(n.sentiment) if n.sentiment is not None else None,
        )
        for n in news
    ]
