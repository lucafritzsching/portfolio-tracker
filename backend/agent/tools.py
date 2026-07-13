"""Tool definitions for the Ollama Qwen agent (function calling / tool use)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
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
from eval.backtest import run_backtest as run_backtest_eval
from models import Position, Transaction, NewsCache
from services.market_data import fetch_and_store_prices, prices_to_dicts, fetch_and_store_news
from services.finder import (
    DEFAULT_MAX_CANDIDATES, load_fallback_universe, parse_mandate, run_predefined_screen, run_screen,
)
from services.nl_target import NLItem, evaluate_nl_target
from services.event_strength import is_relevant

logger = logging.getLogger("agent")


def _to_f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _news_items(news) -> list[NLItem]:
    """NewsCache-Zeilen → NLItems (Headline + Summary) für den NL-Judge."""
    items = []
    for n in news:
        headline = (getattr(n, "headline", "") or "").strip()
        summary = (getattr(n, "summary", "") or "").strip()
        text = f"{headline}. {summary}".strip() if summary else headline
        if text:
            items.append(NLItem(text=text, source=getattr(n, "source", None)))
    return items

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
                    "ticker": {"type": "string", "description": "Börsen-Ticker-Symbol des Unternehmens"},
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
    {
        "type": "function",
        "function": {
            "name": "screen_by_strategy",
            "description": ("Findet Aktien zu einer Freitext-STRATEGIE (Beispiel: Nasdaq Biotech, "
                            "<15 Mrd. Market Cap, >20% Umsatzwachstum). Wandelt das Mandat in harte Filter "
                            "(Börse/Sektor/Market-Cap/Umsatzwachstum) und liefert passende Kandidaten "
                            "(Ticker, Name, Market Cap). Nutze dies, wenn der Nutzer Unternehmen SUCHEN/"
                            "SCREENEN will, statt einen einzelnen Ticker zu nennen."),
            "parameters": {
                "type": "object",
                "properties": {
                    "mandate": {"type": "string", "description": "Die Anlagestrategie als Freitext"},
                },
                "required": ["mandate"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discover_news_movers",
            "description": ("Ticker-FREIE Entdeckung: Welche Aktien bewegen sich HEUTE auffällig "
                            "(Tagesgewinner/-verlierer/meistgehandelt) und was sagen ihre News dazu? "
                            "Deterministische Mover-Quelle (Yahoo-Screen) → beleggebundenes News-Urteil "
                            "je Kandidat → rangierte Liste mit %-Bewegung und zitierten Schlagzeilen. "
                            "Nutze dies, wenn der Nutzer KEINEN Ticker nennt und nach Movern/auffälligen "
                            "News fragt (z. B. 'welche Aktien sind heute mit guten News gestiegen?')."),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["gainers", "losers", "actives"],
                        "description": "gainers = Tagesgewinner, losers = Tagesverlierer, actives = meistgehandelt",
                    },
                    "criterion": {
                        "type": "string",
                        "description": "Optionales Freitext-Kriterium für das News-Urteil (Default: kursrelevante News, die die Bewegung erklären)",
                    },
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_backtest",
            "description": ("Walk-Forward-Backtest des deterministischen Ensemble-Signals für EIN "
                            "Ticker-Symbol: Wie oft traf BUY/HOLD/SELL historisch die 20-Tage-"
                            "Forward-Rendite, verglichen mit der Buy&Hold-Baseline aller Fenster? "
                            "Nutze dies für Fragen nach der ZUVERLÄSSIGKEIT/Güte des Signals "
                            "(z. B. 'wie gut hat das Kaufsignal für AAPL funktioniert?'). "
                            "Dauert ca. 20-60 Sekunden."),
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
            "name": "judge_news",
            "description": ("Beurteilt anhand aktueller Schlagzeilen, ob eine Aktie ein FREITEXT-KRITERIUM "
                            "in Klarsprache erfüllt (Beispiele: hat aktuell eine Turnaround-Story; zuletzt "
                            "gute News). Liefert ein geklammertes Urteil (matches, Signifikanz 0-5), "
                            "Begründung, Belege und den Determinismus-Trace (regex-Basis vs. LLM). Nutze "
                            "dies für News-/Sentiment-/Narrativ-Fragen in natürlicher Sprache."),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker-Symbol"},
                    "criterion": {"type": "string", "description": "Das Freitext-Kriterium in Klarsprache"},
                },
                "required": ["ticker", "criterion"],
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
        self._info_cache: dict[str, dict] = {}

    async def _yf_info(self, ticker: str) -> dict:
        """EIN yf.Ticker(...).info-Abruf pro Ticker und Lauf — geteilt von Fundamentals,
        Kandidaten-Anreicherung und Namens-Lookup. Fehler → leeres Dict (für diesen Lauf)."""
        if ticker not in self._info_cache:
            try:
                self._info_cache[ticker] = await asyncio.to_thread(lambda: yf.Ticker(ticker).info) or {}
            except Exception:
                self._info_cache[ticker] = {}
        return self._info_cache[ticker]

    async def execute(self, tool_name: str, arguments: dict) -> str:
        handlers = {
            "get_historical_prices": self._get_historical_prices,
            "calculate_technical_indicators": self._calculate_technical_indicators,
            "get_fundamentals": self._get_fundamentals,
            "get_news": self._get_news,
            "run_statistical_model": self._run_statistical_model,
            "get_portfolio_context": self._get_portfolio_context,
            "screen_by_strategy": self._screen_by_strategy,
            "judge_news": self._judge_news,
            "run_backtest": self._run_backtest,
            "discover_news_movers": self._discover_news_movers,
        }
        handler = handlers.get(tool_name)
        if not handler:
            logger.warning("Unbekanntes Tool angefragt: %s", tool_name)
            return json.dumps({"error": f"Unbekanntes Tool: {tool_name}"})
        logger.info("Tool-Call: %s(%s)", tool_name, arguments)
        t0 = time.perf_counter()
        try:
            result = await handler(**arguments)
            logger.info("Tool-OK: %s in %.2fs", tool_name, time.perf_counter() - t0)
            return result
        except Exception as e:
            # Traceback ins Server-Log (statt stumm im SSE-String zu verschwinden) + JSON-Fehler zurück.
            logger.exception("Tool-FEHLER: %s(%s)", tool_name, arguments)
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

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
        info = await self._yf_info(ticker)
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

    async def _get_news(self, ticker: str, days: int = 7) -> str:
        ticker = ticker.upper()
        news = await fetch_and_store_news(ticker, self.db, days=days)
        # Relevance filter: Finnhub's company-news feed can include market-wide / multi-tagged articles
        # (e.g. Uniswap/Roku stories under "AAPL"). Keep only headlines that actually mention the company —
        # the same guard judge_news uses — so the agent never reasons over off-topic noise.
        name = await self._company_name(ticker)
        relevant = [
            n for n in news
            if is_relevant(f"{n.headline or ''} {n.summary or ''}", "", ticker, name)
        ]
        if not relevant:
            return json.dumps({
                "ticker": ticker, "article_count": 0,
                "message": "Keine unternehmensspezifischen Nachrichten in diesem Zeitraum gefunden.",
            }, ensure_ascii=False)

        avg_sentiment = sum(float(n.sentiment or 0) for n in relevant) / len(relevant)
        return json.dumps({
            "ticker": ticker,
            "article_count": len(relevant),
            "avg_sentiment": round(avg_sentiment, 3),
            "sentiment_label": "positiv" if avg_sentiment > 0.1 else ("negativ" if avg_sentiment < -0.1 else "neutral"),
            "articles": [
                {
                    "headline": n.headline,
                    "summary": n.summary[:200] if n.summary else None,
                    "published": n.published_at.strftime("%Y-%m-%d"),
                    "sentiment": float(n.sentiment) if n.sentiment else None,
                }
                for n in relevant[:5]
            ],
        }, ensure_ascii=False)

    async def _run_statistical_model(self, ticker: str) -> str:
        ticker = ticker.upper()
        prices = await self._fetch_prices(ticker, "2y")
        if not prices:
            return json.dumps({"error": f"Keine Kursdaten für {ticker}"})

        arima = run_arima_forecast(prices, validate=True)
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

    async def _enrich(self, ticker: str) -> tuple:
        """Echte Fundamentaldaten je Kandidat (Market Cap, Umsatzwachstum, KGV, Name) — gecacht pro Lauf."""
        info = await self._yf_info(ticker)
        if not info:
            return (None, None, None, ticker)
        return (_to_f(info.get("marketCap")), _to_f(info.get("revenueGrowth")),
                _to_f(info.get("trailingPE")), info.get("shortName") or info.get("longName") or ticker)

    async def _screen_by_strategy(self, mandate: str) -> str:
        """Strategie-Finder in EINEM Schritt: Mandat → deterministischer Screen → Fundamentaldaten
        (parallel) → Re-Filter auf echten Werten (Market Cap + Umsatzwachstum) → rangierte Liste.

        Bewusst KEINE Pro-Kandidat-LLM-Verkettung: die teuren Werte kommen aus yfinance (~Sekunden,
        parallel), nicht aus N tool-bestückten 14B-Aufrufen. Market Cap und Umsatzwachstum stehen mit
        echten Zahlen im Ergebnis, sodass der Filter nachvollziehbar/überprüfbar ist.
        """
        parsed = await parse_mandate(mandate)
        candidates, source = await run_screen(parsed.filters)
        if not candidates:
            candidates = load_fallback_universe()
            source = "fallback_universe"

        f = parsed.filters
        max_mc, min_mc, min_growth = f.get("max_market_cap"), f.get("min_market_cap"), f.get("min_revenue_growth")
        pool = candidates[:12]
        enriched = await asyncio.gather(*[self._enrich(c.ticker) for c in pool])

        rows = []
        for c, (mc, rg, pe, name) in zip(pool, enriched):
            mc = mc if mc is not None else c.market_cap
            if max_mc and mc and mc > max_mc:
                continue
            if min_mc and mc and mc < min_mc:
                continue
            if min_growth is not None and rg is not None and rg * 100 < min_growth:
                continue  # Umsatzwachstum „im letzten Jahr" gegen echten Wert geprüft
            row = {
                "ticker": c.ticker,
                "name": name or c.name,
                "market_cap_bn": round(mc / 1e9, 2) if mc else None,
                "revenue_growth_pct": round(rg * 100, 1) if rg is not None else None,
                "pe": round(pe, 1) if pe else None,
            }
            if min_growth is not None and rg is None:
                # Kein Wachstumswert verfügbar → nicht still durchlassen, sondern kennzeichnen.
                row["revenue_growth_unchecked"] = True
            rows.append(row)

        if min_growth is not None:
            # Wachstums-Mandat: geprüfte Kandidaten zuerst, dann nach echtem Wachstum absteigend.
            rows.sort(key=lambda r: (not r.get("revenue_growth_unchecked", False),
                                     r["revenue_growth_pct"] if r["revenue_growth_pct"] is not None else float("-inf")),
                      reverse=True)
        else:
            rows.sort(key=lambda r: (r["market_cap_bn"] or 0), reverse=True)

        return json.dumps({
            "mandate": mandate,
            "parsed_filters": f,
            "nl_criterion": parsed.nl_criterion,
            "source": source,
            "match_count": len(rows),
            "candidates": rows[:DEFAULT_MAX_CANDIDATES],
            "hinweis": ("market_cap_bn und revenue_growth_pct sind echte Fundamentaldaten, nach dem Screen "
                        "erneut geprüft. Kandidaten mit revenue_growth_unchecked=true haben KEINEN "
                        "verfügbaren Wachstumswert — als ungeprüft benennen, nicht behaupten."),
        }, ensure_ascii=False)

    async def _company_name(self, ticker: str) -> str:
        """Company name for the relevance filter (cached per run). Falls back to '' on failure."""
        info = await self._yf_info(ticker)
        return info.get("shortName") or info.get("longName") or ""

    async def _judge_news(self, ticker: str, criterion: str) -> str:
        """NL-Urteil: aktuelle Schlagzeilen gegen ein Freitext-Kriterium (sektor-agnostisch, beleggebunden).

        Filtert die News per Ticker/Name auf das Unternehmen (sonst kann der Finnhub-Feed themenfremde
        Artikel einschleusen), dann beurteilt das LLM das Kriterium und muss echte Schlagzeilen zitieren.
        """
        ticker = ticker.upper()
        news = await fetch_and_store_news(ticker, self.db, days=14)
        if not news:
            return json.dumps({
                "ticker": ticker, "criterion": criterion, "matches": False,
                "message": "Keine aktuellen Schlagzeilen gefunden — keine NL-Beurteilung möglich.",
            }, ensure_ascii=False)
        items = _news_items(news)
        name = await self._company_name(ticker)
        verdict = await evaluate_nl_target(criterion, items, ticker=ticker, name=name, mode="fast")
        return json.dumps({
            "ticker": ticker,
            "criterion": criterion,
            "matches": verdict.matches,
            "significance": verdict.strength,
            "reason": verdict.reason,
            "evidence": verdict.evidence[:3],
            "trace": {
                "llm_strength": verdict.llm_strength,
                "final": verdict.strength,
                "n_evidence_cited": len(verdict.evidence),
                "source": verdict.source,
            },
            "headlines_checked": len(items),
        }, ensure_ascii=False)

    DISCOVER_JUDGE_LIMIT = 5   # wie viele Mover den NL-Judge erreichen (Compute-Budget, ~5-8s je Urteil)

    async def _discover_news_movers(self, direction: str = "gainers", criterion: str = "") -> str:
        """Ticker-freie News-Discovery: deterministische Mover-Quelle → beleggebundenes NL-Urteil.

        `is_relevant` kann nicht rückwärts entdecken (braucht immer einen Kandidaten) — deshalb
        liefert der Yahoo-Mover-Screen die Kandidaten, und erst DANACH urteilt der NL-Judge über
        deren News (dieselbe Grounding-Garantie wie judge_news: nur echte Schlagzeilen zählen).
        """
        movers = await run_predefined_screen(direction, count=10)
        if not movers:
            return json.dumps({
                "error": f"Mover-Screen '{direction}' nicht verfügbar (Yahoo nicht erreichbar oder unbekannte Richtung).",
            }, ensure_ascii=False)

        crit = (criterion or "").strip() or "aktuelle kursrelevante Nachrichten, die die Kursbewegung erklären"
        judged = []
        for m in movers[: self.DISCOVER_JUDGE_LIMIT]:
            news = await fetch_and_store_news(m["ticker"], self.db, days=7)
            items = _news_items(news)
            if items:
                v = await evaluate_nl_target(crit, items, ticker=m["ticker"], name=m["name"] or "", mode="fast")
                judged.append({**m, "matches": v.matches, "significance": v.strength,
                               "reason": v.reason, "evidence": v.evidence[:2]})
            else:
                judged.append({**m, "matches": False, "significance": 0,
                               "reason": "Keine unternehmensspezifischen Schlagzeilen gefunden.",
                               "evidence": []})
        judged.sort(key=lambda r: (r["matches"], r["significance"], abs(r["change_pct"] or 0)), reverse=True)

        return json.dumps({
            "direction": direction,
            "criterion": crit,
            "source": "yahoo_predefined_screen",
            "candidates": judged,
            "weitere_ticker_ungeprueft": [m["ticker"] for m in movers[self.DISCOVER_JUDGE_LIMIT:]],
            "hinweis": ("Urteile sind beleggebunden (evidence = echte Schlagzeilen). Kandidaten ohne "
                        "matches haben keine belegbaren News zum Kriterium — %-Bewegung trotzdem nennen."),
        }, ensure_ascii=False)

    async def _run_backtest(self, ticker: str) -> str:
        """Walk-Forward-Backtest für EIN Ticker (step=10 statt 5: halbe Fensterzahl → Chat-taugliche
        Laufzeit). Jedes Fenster fittet ARIMA+RF — das läuft im Eval-Modul via to_thread."""
        ticker = ticker.upper()
        res = await run_backtest_eval(self.db, [ticker], horizon_days=20, step_days=10)
        return json.dumps({
            "ticker": ticker,
            "params": res["params"],
            "results": res["per_ticker"].get(ticker, {}),
            "hinweis": ("Signal je Fenster vs. 20-Tage-Forward-Rendite; 'baseline' = Buy&Hold über "
                        "ALLE Fenster — BUY ist nur gut, wenn es die Baseline schlägt. Kleine n → "
                        "nicht signifikant, als Tendenz formulieren."),
        }, ensure_ascii=False)

    async def _fetch_prices(self, ticker: str, period: str) -> list[dict]:
        """Fetch prices via the shared service, cached per analysis to avoid repeat work.

        Nur nach Ticker gekeyt: der Service lädt nie kürzer als 2y (Superset), d. h. ein
        vorheriger "1mo"-Abruf kann einem späteren "2y"-Abruf keine Daten wegnehmen.
        """
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
