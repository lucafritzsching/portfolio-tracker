"""Reusable market-data fetch + cache services.

Shared by the HTTP routers (routers/market_data.py) and the agent pipeline so there
is exactly one place that talks to yfinance/Finnhub and one caching policy. All
blocking yfinance calls run via asyncio.to_thread to keep the event loop free.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, date, timedelta

import httpx
import yfinance as yf
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import PriceHistory, FundamentalsCache, NewsCache

logger = logging.getLogger("agent")

# Daily OHLCV bars: cache counts as fresh if the newest stored bar is within this
# many calendar days (covers weekends/holidays without refetching every request).
PRICE_FRESH_DAYS = 3
FUNDAMENTALS_TTL = timedelta(hours=12)
NEWS_TTL = timedelta(hours=1)


def _cell(row, col):
    """yfinance may return MultiIndex columns (Series per ticker) or flat scalars."""
    val = row[col]
    return val.iloc[0] if hasattr(val, "iloc") else val


# ── Prices ────────────────────────────────────────────────────────────────────

async def fetch_and_store_prices(
    ticker: str, db: AsyncSession, period: str = "2y", force: bool = False
) -> list[PriceHistory]:
    ticker = ticker.upper()
    latest = (
        await db.execute(
            select(PriceHistory)
            .where(PriceHistory.ticker == ticker)
            .order_by(PriceHistory.date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if not force and latest and (date.today() - latest.date).days <= PRICE_FRESH_DAYS:
        return await _load_prices(ticker, db)

    try:
        # wait_for setzt eine Obergrenze: bei einem hängenden Download gibt der
        # Request Kontrolle zurück (der Hintergrund-Thread läuft noch aus, kann aber
        # nicht hart abgebrochen werden) statt den Worker unbegrenzt zu blockieren.
        df = await asyncio.wait_for(
            asyncio.to_thread(
                yf.download, ticker, period=period, auto_adjust=True, progress=False
            ),
            timeout=settings.yfinance_timeout,
        )
    except asyncio.TimeoutError:
        # On a fetch failure fall back to whatever is cached (demo robustness).
        logger.warning("yfinance-Download Timeout (%ss) für %s — nutze Cache",
                       settings.yfinance_timeout, ticker)
        return await _load_prices(ticker, db)
    except Exception:
        logger.warning("yfinance-Download fehlgeschlagen für %s — nutze Cache", ticker, exc_info=True)
        return await _load_prices(ticker, db)

    if df is None or df.empty:
        return await _load_prices(ticker, db)

    await db.execute(delete(PriceHistory).where(PriceHistory.ticker == ticker))
    for idx, row in df.iterrows():
        db.add(PriceHistory(
            ticker=ticker,
            date=idx.date(),
            open=float(_cell(row, "Open")),
            high=float(_cell(row, "High")),
            low=float(_cell(row, "Low")),
            close=float(_cell(row, "Close")),
            volume=int(_cell(row, "Volume")),
        ))
    await db.commit()
    return await _load_prices(ticker, db)


async def _load_prices(ticker: str, db: AsyncSession) -> list[PriceHistory]:
    return (
        await db.execute(
            select(PriceHistory)
            .where(PriceHistory.ticker == ticker)
            .order_by(PriceHistory.date)
        )
    ).scalars().all()


def prices_to_dicts(rows: list[PriceHistory]) -> list[dict]:
    """Convert ORM rows to the dict shape the data-science layer expects."""
    return [
        {
            "date": str(r.date),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": r.volume,
        }
        for r in rows
    ]


# ── Fundamentals ──────────────────────────────────────────────────────────────

async def fetch_and_store_fundamentals(
    ticker: str, db: AsyncSession, force: bool = False
) -> FundamentalsCache | None:
    ticker = ticker.upper()
    cached = (
        await db.execute(select(FundamentalsCache).where(FundamentalsCache.ticker == ticker))
    ).scalar_one_or_none()

    if not force and cached and (datetime.utcnow() - cached.fetched_at) < FUNDAMENTALS_TTL:
        return cached

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(lambda: yf.Ticker(ticker).info),
            timeout=settings.yfinance_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("yfinance-Fundamentals Timeout (%ss) für %s — nutze Cache",
                       settings.yfinance_timeout, ticker)
        return cached
    except Exception:
        logger.warning("yfinance-Fundamentals fehlgeschlagen für %s — nutze Cache", ticker, exc_info=True)
        return cached

    if not info or info.get("regularMarketPrice") is None:
        return cached

    fields = dict(
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
        for key, value in fields.items():
            setattr(cached, key, value)
        obj = cached
    else:
        obj = FundamentalsCache(ticker=ticker, **fields)
        db.add(obj)
    await db.commit()
    return obj


# ── News ──────────────────────────────────────────────────────────────────────

async def fetch_and_store_news(
    ticker: str, db: AsyncSession, days: int = 14, force: bool = False
) -> list[NewsCache]:
    ticker = ticker.upper()
    cutoff = datetime.utcnow() - timedelta(days=days)

    existing = (
        await db.execute(
            select(NewsCache)
            .where(NewsCache.ticker == ticker, NewsCache.published_at >= cutoff)
            .order_by(NewsCache.published_at.desc())
        )
    ).scalars().all()

    if not force and existing:
        newest = max(n.published_at for n in existing)
        if (datetime.utcnow() - newest) < NEWS_TTL:
            return existing

    if settings.finnhub_api_key:
        frm = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        to = datetime.utcnow().strftime("%Y-%m-%d")
        try:
            url = (
                f"https://finnhub.io/api/v1/company-news?symbol={ticker}"
                f"&from={frm}&to={to}&token={settings.finnhub_api_key}"
            )
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                articles = resp.json() if resp.is_success else []
        except Exception:
            logger.warning("Finnhub-News-Abruf fehlgeschlagen für %s", ticker, exc_info=True)
            articles = []

        existing_urls = {n.url for n in existing if n.url}
        for article in articles[:20]:
            article_url = article.get("url")
            if article_url and article_url in existing_urls:
                continue  # dedup — avoid piling up duplicate rows on repeated fetches
            db.add(NewsCache(
                ticker=ticker,
                headline=article.get("headline", ""),
                summary=article.get("summary"),
                url=article_url,
                source=article.get("source"),
                published_at=datetime.fromtimestamp(article.get("datetime", 0)),
                sentiment=keyword_sentiment(
                    article.get("headline", "") + " " + (article.get("summary") or "")
                ),
            ))
        await db.commit()

    return (
        await db.execute(
            select(NewsCache)
            .where(NewsCache.ticker == ticker, NewsCache.published_at >= cutoff)
            .order_by(NewsCache.published_at.desc())
            .limit(20)
        )
    ).scalars().all()


def keyword_sentiment(text: str) -> float:
    """Naive keyword-based sentiment in [-1, 1]. Offline fallback when no LLM scoring is available."""
    positive = ["gewinn", "wachstum", "rekord", "stark", "beat", "profit", "growth",
                "record", "strong", "rise", "surge", "bullish"]
    negative = ["verlust", "rückgang", "schwach", "miss", "decline", "weak", "fall",
                "drop", "bearish", "warn", "cut", "risk"]
    text_lower = text.lower()
    score = sum(1 for w in positive if w in text_lower) - sum(1 for w in negative if w in text_lower)
    return max(-1.0, min(1.0, score * 0.25))
