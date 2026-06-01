"""Tool definitions for the Ollama Qwen agent (function calling / tool use)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.data_science import (
    calculate_technical_indicators,
    run_arima_forecast,
    run_ml_signal,
)
from models import Position, Transaction, NewsCache
from services.market_data import fetch_and_store_prices, prices_to_dicts

# ── Tool schemas for Ollama (OpenAI-compatible format) ───────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_historical_prices",
            "description": "Lädt historische Tagesschlusskurse (OHLCV) für ein Ticker-Symbol. Gibt die letzten N Tage zurück.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker-Symbol, z.B. AAPL"},
                    "period": {"type": "string", "enum": ["1mo", "3mo", "6mo", "1y", "2y"], "description": "Zeitraum"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_technical_indicators",
            "description": "Berechnet technische Indikatoren: RSI, MACD, Bollinger Bands, SMA 20/50/200, EMA 12/26. Gibt auch ein Trend-Signal (BULLISH/BEARISH/NEUTRAL) zurück.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker-Symbol"},
                    "period": {"type": "string", "enum": ["6mo", "1y", "2y"], "description": "Zeitraum für die Berechnung"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fundamentals",
            "description": "Ruft Fundamentaldaten ab: KGV (P/E), Marktkapitalisierung, EPS, Umsatzwachstum, 52-Wochen-Hoch/Tief, Dividendenrendite, Beta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker-Symbol"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "Ruft aktuelle Nachrichten und deren Sentiment-Score für ein Unternehmen ab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker-Symbol"},
                    "days": {"type": "integer", "description": "Nachrichten der letzten N Tage", "default": 7},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_statistical_model",
            "description": "Führt statistische/ML-Modelle durch: ARIMA-Zeitreihenprognose für 7 und 30 Tage sowie ein Random-Forest-Klassifikator für Buy/Hold/Sell-Signale.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker-Symbol"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_context",
            "description": "Gibt den aktuellen Portfolio-Kontext für einen Ticker zurück: Anzahl Aktien, durchschnittlicher Kaufpreis, unrealisierter P&L, Portfoliogewicht.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker-Symbol"},
                },
                "required": ["ticker"],
            },
        },
    },
]


# ── Tool executor ─────────────────────────────────────────────────────────────

class ToolExecutor:
    def __init__(self, db: AsyncSession, current_prices: dict[str, float] | None = None):
        self.db = db
        self.current_prices = current_prices or {}
        self._price_cache: dict[str, list[dict]] = {}

    async def execute(self, tool_name: str, arguments: dict) -> str:
        handlers = {
            "get_historical_prices": self._get_historical_prices,
            "calculate_technical_indicators": self._calculate_technical_indicators,
            "get_fundamentals": self._get_fundamentals,
            "get_news": self._get_news,
            "run_statistical_model": self._run_statistical_model,
            "get_portfolio_context": self._get_portfolio_context,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unbekanntes Tool: {tool_name}"})
        try:
            return await handler(**arguments)
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _get_historical_prices(self, ticker: str, period: str = "1y") -> str:
        ticker = ticker.upper()
        prices = await self._fetch_prices(ticker, period)

        if not prices:
            return json.dumps({"error": f"Keine Kursdaten für {ticker}"})

        # Return summary (not all rows, to keep context small)
        recent = prices[-30:]
        return json.dumps({
            "ticker": ticker,
            "total_days": len(prices),
            "period_start": prices[0]["date"],
            "period_end": prices[-1]["date"],
            "current_close": prices[-1]["close"],
            "30d_high": max(p["high"] for p in recent),
            "30d_low": min(p["low"] for p in recent),
            "30d_avg_volume": int(sum(p["volume"] for p in recent) / len(recent)),
            "recent_prices": [{"date": p["date"], "close": p["close"]} for p in prices[-10:]],
        })

    async def _calculate_technical_indicators(self, ticker: str, period: str = "1y") -> str:
        ticker = ticker.upper()
        prices = await self._fetch_prices(ticker, period)
        if not prices:
            return json.dumps({"error": f"Keine Kursdaten für {ticker}"})

        indicators = calculate_technical_indicators(prices)
        result = {k: v for k, v in asdict(indicators).items() if v is not None}
        result["interpretation"] = _interpret_indicators(indicators)
        return json.dumps(result)

    async def _get_fundamentals(self, ticker: str) -> str:
        ticker = ticker.upper()
        try:
            info = await asyncio.to_thread(lambda: yf.Ticker(ticker).info)
            if not info:
                return json.dumps({"error": "Keine Daten"})
            return json.dumps({
                "ticker": ticker,
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "market_cap": info.get("marketCap"),
                "eps": info.get("trailingEps"),
                "eps_growth": info.get("earningsGrowth"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "analyst_target_price": info.get("targetMeanPrice"),
                "recommendation": info.get("recommendationKey"),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _get_news(self, ticker: str, days: int = 7) -> str:
        ticker = ticker.upper()
        cutoff = datetime.utcnow() - timedelta(days=days)
        result = await self.db.execute(
            select(NewsCache)
            .where(NewsCache.ticker == ticker, NewsCache.published_at >= cutoff)
            .order_by(NewsCache.published_at.desc())
            .limit(10)
        )
        news = result.scalars().all()
        if not news:
            return json.dumps({"ticker": ticker, "news": [], "message": "Keine gecachten News. Bitte zuerst /market-data/news/{ticker} aufrufen."})

        avg_sentiment = sum(float(n.sentiment or 0) for n in news) / len(news)
        return json.dumps({
            "ticker": ticker,
            "article_count": len(news),
            "avg_sentiment": round(avg_sentiment, 3),
            "sentiment_label": "positiv" if avg_sentiment > 0.1 else ("negativ" if avg_sentiment < -0.1 else "neutral"),
            "articles": [
                {
                    "headline": n.headline,
                    "summary": n.summary[:200] if n.summary else None,
                    "published": n.published_at.strftime("%Y-%m-%d"),
                    "sentiment": float(n.sentiment) if n.sentiment else None,
                }
                for n in news[:5]
            ],
        })

    async def _run_statistical_model(self, ticker: str) -> str:
        ticker = ticker.upper()
        prices = await self._fetch_prices(ticker, "2y")
        if not prices:
            return json.dumps({"error": f"Keine Kursdaten für {ticker}"})

        arima = run_arima_forecast(prices)
        ml = run_ml_signal(prices)

        # Consensus signal
        signals = [arima.signal, ml.signal]
        buy_count = signals.count("BUY")
        sell_count = signals.count("SELL")
        consensus = "BUY" if buy_count >= 2 else ("SELL" if sell_count >= 2 else "HOLD")

        return json.dumps({
            "ticker": ticker,
            "arima": {
                "method": arima.method,
                "forecast_7d": arima.forecast_7d,
                "forecast_30d": arima.forecast_30d,
                "signal": arima.signal,
                "confidence": arima.confidence,
                "details": arima.details,
            },
            "random_forest": {
                "method": ml.method,
                "signal": ml.signal,
                "confidence": ml.confidence,
                "details": ml.details,
            },
            "consensus_signal": consensus,
        })

    async def _get_portfolio_context(self, ticker: str) -> str:
        ticker = ticker.upper()
        result = await self.db.execute(select(Position).where(Position.ticker == ticker))
        pos = result.scalar_one_or_none()
        if not pos:
            return json.dumps({"ticker": ticker, "message": "Position nicht im Portfolio"})

        # Avg buy price from transactions
        tx_result = await self.db.execute(
            select(Transaction)
            .where(Transaction.ticker == ticker, Transaction.type == "buy")
        )
        buy_txs = tx_result.scalars().all()
        if buy_txs:
            total_cost = sum(float(t.shares) * float(t.price) for t in buy_txs)
            total_shares = sum(float(t.shares) for t in buy_txs)
            avg_buy = total_cost / total_shares if total_shares > 0 else None
        else:
            avg_buy = float(pos.manual_buy_price) if pos.manual_buy_price else None

        current_price = self.current_prices.get(ticker)
        unrealized_pnl = None
        unrealized_pnl_pct = None
        if avg_buy and current_price:
            unrealized_pnl = (current_price - avg_buy) * float(pos.shares)
            unrealized_pnl_pct = (current_price - avg_buy) / avg_buy * 100

        # Portfolio weight — must be relative to ALL positions, not just this one.
        all_positions = (await self.db.execute(select(Position))).scalars().all()
        total_value = sum(
            self.current_prices.get(p.ticker, 0) * float(p.shares)
            for p in all_positions
        )
        position_value = (current_price or 0) * float(pos.shares)
        portfolio_weight = (position_value / total_value * 100) if total_value > 0 else None

        return json.dumps({
            "ticker": ticker,
            "name": pos.name,
            "shares": float(pos.shares),
            "sector": pos.sector,
            "avg_buy_price": round(avg_buy, 4) if avg_buy else None,
            "current_price": current_price,
            "position_value": round(position_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2) if unrealized_pnl_pct is not None else None,
            "note": pos.note,
        })

    async def _fetch_prices(self, ticker: str, period: str) -> list[dict]:
        """Fetch prices via the shared service, cached per analysis to avoid repeat work."""
        ticker = ticker.upper()
        if ticker in self._price_cache:
            return self._price_cache[ticker]
        rows = await fetch_and_store_prices(ticker, self.db, period=period)
        prices = prices_to_dicts(rows)
        self._price_cache[ticker] = prices
        return prices


def _interpret_indicators(ind) -> str:
    parts = []
    if ind.rsi_14:
        if ind.rsi_14 > 70:
            parts.append(f"RSI {ind.rsi_14:.1f}: überkauft (>70)")
        elif ind.rsi_14 < 30:
            parts.append(f"RSI {ind.rsi_14:.1f}: überverkauft (<30)")
        else:
            parts.append(f"RSI {ind.rsi_14:.1f}: neutral")

    if ind.macd and ind.macd_signal:
        if ind.macd > ind.macd_signal:
            parts.append("MACD über Signal-Linie (bullish)")
        else:
            parts.append("MACD unter Signal-Linie (bearish)")

    if ind.current_price and ind.bb_upper and ind.bb_lower:
        if ind.current_price > ind.bb_upper:
            parts.append("Kurs über oberem Bollinger Band (überkauft)")
        elif ind.current_price < ind.bb_lower:
            parts.append("Kurs unter unterem Bollinger Band (überverkauft)")

    if ind.price_vs_sma200:
        parts.append(f"Kurs {ind.price_vs_sma200:+.1f}% gegenüber 200-Tage-SMA")

    return "; ".join(parts) if parts else "Keine Interpretation verfügbar"
