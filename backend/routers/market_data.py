from datetime import datetime, timedelta
import yfinance as yf
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import PriceHistory, FundamentalsCache, NewsCache
from schemas import PriceHistoryOut, FundamentalsOut, NewsItemOut
from config import settings

router = APIRouter(prefix="/market-data", tags=["market-data"])

CACHE_TTL_FUNDAMENTALS = timedelta(hours=12)
CACHE_TTL_NEWS = timedelta(hours=1)
CACHE_TTL_PRICES = timedelta(hours=1)


@router.get("/history/{ticker}", response_model=list[PriceHistoryOut])
async def get_price_history(
    ticker: str,
    period: str = Query("1y", description="1mo, 3mo, 6mo, 1y, 2y, 5y"),
    db: AsyncSession = Depends(get_db),
):
    ticker = ticker.upper()

    # Check cache freshness: if most recent row is within TTL, return cache
    result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.ticker == ticker)
        .order_by(PriceHistory.date.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    if latest and (datetime.utcnow().date() - latest.date) < timedelta(hours=1):
        all_rows = await db.execute(
            select(PriceHistory).where(PriceHistory.ticker == ticker).order_by(PriceHistory.date)
        )
        return all_rows.scalars().all()

    # Fetch fresh data from yfinance
    try:
        df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    except Exception:
        raise HTTPException(502, f"Kursdaten für {ticker} konnten nicht geladen werden")

    if df.empty:
        raise HTTPException(404, f"Keine Kursdaten für {ticker} gefunden")

    # Clear stale cache
    await db.execute(delete(PriceHistory).where(PriceHistory.ticker == ticker))

    rows = []
    for idx, row in df.iterrows():
        ph = PriceHistory(
            ticker=ticker,
            date=idx.date(),
            open=float(row["Open"].iloc[0] if hasattr(row["Open"], "iloc") else row["Open"]),
            high=float(row["High"].iloc[0] if hasattr(row["High"], "iloc") else row["High"]),
            low=float(row["Low"].iloc[0] if hasattr(row["Low"], "iloc") else row["Low"]),
            close=float(row["Close"].iloc[0] if hasattr(row["Close"], "iloc") else row["Close"]),
            volume=int(row["Volume"].iloc[0] if hasattr(row["Volume"], "iloc") else row["Volume"]),
        )
        db.add(ph)
        rows.append(ph)

    await db.commit()
    return rows


@router.get("/fundamentals/{ticker}", response_model=FundamentalsOut)
async def get_fundamentals(ticker: str, db: AsyncSession = Depends(get_db)):
    ticker = ticker.upper()

    result = await db.execute(select(FundamentalsCache).where(FundamentalsCache.ticker == ticker))
    cached = result.scalar_one_or_none()
    if cached and (datetime.utcnow() - cached.fetched_at) < CACHE_TTL_FUNDAMENTALS:
        return FundamentalsOut(
            ticker=ticker,
            pe_ratio=float(cached.pe_ratio) if cached.pe_ratio else None,
            market_cap=float(cached.market_cap) if cached.market_cap else None,
            eps=float(cached.eps) if cached.eps else None,
            revenue_growth=float(cached.revenue_growth) if cached.revenue_growth else None,
            fifty_two_week_high=float(cached.fifty_two_week_high) if cached.fifty_two_week_high else None,
            fifty_two_week_low=float(cached.fifty_two_week_low) if cached.fifty_two_week_low else None,
            dividend_yield=float(cached.dividend_yield) if cached.dividend_yield else None,
            beta=float(cached.beta) if cached.beta else None,
            fetched_at=cached.fetched_at,
        )

    try:
        info = yf.Ticker(ticker).info
    except Exception:
        raise HTTPException(502, f"Fundamentaldaten für {ticker} konnten nicht geladen werden")

    if not info or info.get("regularMarketPrice") is None:
        raise HTTPException(404, f"Keine Fundamentaldaten für {ticker}")

    data = FundamentalsCache(
        ticker=ticker,
        pe_ratio=info.get("trailingPE"),
        market_cap=info.get("marketCap"),
        eps=info.get("trailingEps"),
        revenue_growth=info.get("revenueGrowth"),
        fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
        fifty_two_week_low=info.get("fiftyTwoWeekLow"),
        dividend_yield=info.get("dividendYield"),
        beta=info.get("beta"),
        fetched_at=datetime.utcnow(),
    )
    if cached:
        for col in ["pe_ratio", "market_cap", "eps", "revenue_growth",
                    "fifty_two_week_high", "fifty_two_week_low", "dividend_yield", "beta", "fetched_at"]:
            setattr(cached, col, getattr(data, col))
    else:
        db.add(data)
    await db.commit()

    return FundamentalsOut(
        ticker=ticker,
        pe_ratio=info.get("trailingPE"),
        market_cap=info.get("marketCap"),
        eps=info.get("trailingEps"),
        revenue_growth=info.get("revenueGrowth"),
        fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
        fifty_two_week_low=info.get("fiftyTwoWeekLow"),
        dividend_yield=info.get("dividendYield"),
        beta=info.get("beta"),
        fetched_at=datetime.utcnow(),
    )


@router.get("/news/{ticker}", response_model=list[NewsItemOut])
async def get_news(ticker: str, days: int = Query(7, le=30), db: AsyncSession = Depends(get_db)):
    ticker = ticker.upper()

    cutoff = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(NewsCache)
        .where(NewsCache.ticker == ticker, NewsCache.published_at >= cutoff)
        .order_by(NewsCache.published_at.desc())
    )
    cached_news = result.scalars().all()

    # Return cache if we have recent news (fetched within last hour)
    if cached_news:
        most_recent_fetch = max(n.published_at for n in cached_news)
        if (datetime.utcnow() - most_recent_fetch) < CACHE_TTL_NEWS:
            return [NewsItemOut(
                id=n.id, ticker=n.ticker, headline=n.headline, summary=n.summary,
                url=n.url, source=n.source, published_at=n.published_at, sentiment=float(n.sentiment) if n.sentiment else None
            ) for n in cached_news]

    # Fetch from Finnhub news endpoint
    from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = datetime.utcnow().strftime("%Y-%m-%d")
    news_items = []

    if settings.finnhub_api_key:
        try:
            url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={from_date}&to={to_date}&token={settings.finnhub_api_key}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                articles = resp.json() if resp.is_success else []
        except Exception:
            articles = []

        for article in articles[:20]:
            sentiment = _simple_sentiment(article.get("headline", "") + " " + article.get("summary", ""))
            item = NewsCache(
                ticker=ticker,
                headline=article.get("headline", ""),
                summary=article.get("summary"),
                url=article.get("url"),
                source=article.get("source"),
                published_at=datetime.fromtimestamp(article.get("datetime", 0)),
                sentiment=sentiment,
            )
            db.add(item)
            news_items.append(item)

    await db.commit()

    result2 = await db.execute(
        select(NewsCache)
        .where(NewsCache.ticker == ticker, NewsCache.published_at >= cutoff)
        .order_by(NewsCache.published_at.desc())
        .limit(20)
    )
    final = result2.scalars().all()
    return [NewsItemOut(
        id=n.id, ticker=n.ticker, headline=n.headline, summary=n.summary,
        url=n.url, source=n.source, published_at=n.published_at, sentiment=float(n.sentiment) if n.sentiment else None
    ) for n in final]


def _simple_sentiment(text: str) -> float:
    """Very basic keyword-based sentiment score between -1.0 and 1.0."""
    positive = ["gewinn", "wachstum", "rekord", "stark", "beat", "profit", "growth", "record", "strong", "rise", "surge", "bullish"]
    negative = ["verlust", "rückgang", "schwach", "miss", "decline", "weak", "fall", "drop", "bearish", "warn", "cut", "risk"]
    text_lower = text.lower()
    score = sum(1 for w in positive if w in text_lower) - sum(1 for w in negative if w in text_lower)
    return max(-1.0, min(1.0, score * 0.25))
