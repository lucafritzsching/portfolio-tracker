"""Deterministic screener orchestration for NASDAQ biotech candidates.

The screener searches a small curated universe first. That keeps demos stable and
avoids turning the app into a rate-limit-heavy full-market crawler.

This module owns **I/O + orchestration** (universe, fetching, the funnel) plus the
Alt-A technical score. The pure Alt-B scoring core lives in ``alt_b_signal.py`` and
the shared data types in ``screening_types.py``. The Alt-B names are re-imported here
so existing callers (``from services.screener import score_alt_b`` / ``InsiderBuy``)
keep working.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx

from services.event_strength import sector_regime
from services.screening_types import (
    CONTEXT_DAYS,
    MIN_INSIDER_VALUE,
    InsiderBuy,
    StrategyScore,
    _as_date,
    _to_float,
)
from services.alt_b_signal import has_current_turnaround_signal, score_alt_b

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_MARKET_CAP = 15_000_000_000
TURNAROUND_DAYS = 7
INSIDER_CONTEXT_DAYS = 180

# Re-exported for backwards compatibility (callers historically imported these here).
__all__ = [
    "InsiderBuy",
    "StrategyScore",
    "ScreenerStock",
    "ScreenerCandidate",
    "ScreenerRun",
    "ScreenerFunnelStep",
    "ScreenerWindows",
    "passes_base_filter",
    "load_biotech_universe",
    "score_alt_a",
    "score_alt_b",
    "has_current_turnaround_signal",
    "fetch_insider_buys",
    "screen_biotech_turnaround",
]


@dataclass(frozen=True)
class ScreenerStock:
    ticker: str
    name: str
    exchange: str
    industry: str


@dataclass
class ScreenerCandidate:
    ticker: str
    name: str
    exchange: str
    industry: str
    market_cap: float | None
    revenue_growth: float | None
    performance_90d: float | None
    alt_a: StrategyScore
    alt_b: StrategyScore
    turnaround_news: list[str]
    insider_buys: list[InsiderBuy]
    insider_context_buys: list[InsiderBuy] = field(default_factory=list)
    biotech_events: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScreenerFunnelStep:
    label: str
    count: int
    detail: str


@dataclass(frozen=True)
class ScreenerWindows:
    event_days: int = TURNAROUND_DAYS
    context_days: int = CONTEXT_DAYS
    insider_context_days: int = INSIDER_CONTEXT_DAYS


@dataclass
class ScreenerRun:
    universe_count: int
    filter_funnel: list[ScreenerFunnelStep]
    windows: ScreenerWindows
    candidates: list[ScreenerCandidate]


def load_biotech_universe() -> list[ScreenerStock]:
    path = Path(__file__).resolve().parents[1] / "data" / "biotech_universe.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        ScreenerStock(
            ticker=str(row["ticker"]).upper(),
            name=str(row["name"]),
            exchange=str(row["exchange"]),
            industry=str(row["industry"]),
        )
        for row in rows
    ]


def passes_base_filter(
    stock: ScreenerStock,
    fundamentals: Any,
    max_market_cap: float = MAX_MARKET_CAP,
) -> bool:
    market_cap = _to_float(getattr(fundamentals, "market_cap", None))
    revenue_growth = _to_float(getattr(fundamentals, "revenue_growth", None))
    industry = stock.industry.lower()
    # Pre-Revenue-Fallback: viele echte Biotechs haben (noch) keinen Umsatz
    # (revenue_growth == None). Die nicht ausschließen — nur klar schrumpfende
    # Umsätze (<= 0) fallen raus.
    growth_ok = revenue_growth is None or revenue_growth > 0
    return (
        stock.exchange.upper() == "NASDAQ"
        and ("biotech" in industry or "biotechnology" in industry)
        and market_cap is not None
        and market_cap <= max_market_cap
        and growth_ok
    )


def score_alt_a(prices: list[Any]) -> StrategyScore:
    closes = [_to_float(getattr(p, "close", None)) for p in sorted(prices, key=lambda p: _as_date(getattr(p, "date")))]
    closes = [c for c in closes if c is not None]
    if len(closes) < 30:
        return StrategyScore("ALT_A", 0, "Zu wenig Kursdaten", ["Mindestens 30 Kursdaten nötig"], [])

    current = closes[-1]
    sma20 = _mean(closes[-20:])
    std20 = _stddev(closes[-20:])
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    sma50 = _mean(closes[-50:]) if len(closes) >= 50 else None
    sma200 = _mean(closes[-200:]) if len(closes) >= 200 else None

    score = 0
    reasons: list[str] = []
    evidence = [f"Kurs: {current:.2f}", f"Bollinger Mitte: {sma20:.2f}"]

    if current > sma20:
        score += 30
        reasons.append("Kurs liegt über der Bollinger-Mittellinie")

    band_width = upper - lower
    if band_width > 0:
        band_position = (current - lower) / band_width
        evidence.append(f"Bollinger-Position: {band_position * 100:.0f}%")
        if band_position >= 0.60:
            score += 25
            reasons.append("Bollinger-Position ist positiv")

    if sma50 is not None and current > sma50:
        score += 20
        reasons.append("Kurs liegt über SMA50")

    if sma200 is not None and current > sma200:
        score += 25
        reasons.append("Kurs liegt über SMA200")

    score = min(score, 100)
    return StrategyScore(
        strategy="ALT_A",
        score=score,
        label=_alt_a_label(score),
        reasons=reasons,
        evidence=evidence,
    )


async def fetch_insider_buys(
    ticker: str,
    days: int = TURNAROUND_DAYS,
    min_value: float = MIN_INSIDER_VALUE,
) -> list[InsiderBuy]:
    from config import settings

    if not settings.finnhub_api_key:
        return []

    today = datetime.utcnow().date()
    frm = today - timedelta(days=days)
    url = (
        "https://finnhub.io/api/v1/stock/insider-transactions"
        f"?symbol={ticker.upper()}&from={frm.isoformat()}&to={today.isoformat()}"
        f"&token={settings.finnhub_api_key}"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json() if resp.is_success else {}
    except Exception:
        return []

    rows = data.get("data", data if isinstance(data, list) else [])
    buys: list[InsiderBuy] = []
    for row in rows:
        code = str(row.get("transactionCode") or row.get("transaction_code") or "").upper()
        change = _to_float(row.get("change"))
        if code != "P" or change is None or change <= 0:
            continue
        price = _to_float(row.get("transactionPrice") or row.get("transaction_price") or row.get("price"))
        buy = InsiderBuy(
            name=str(row.get("name") or "Insider"),
            transaction_date=_parse_date(row.get("transactionDate") or row.get("transaction_date")),
            filing_date=_parse_date(row.get("filingDate") or row.get("filing_date")),
            shares=change,
            price=price,
        )
        if buy.value is not None and buy.value < min_value:
            continue
        buys.append(buy)
    return buys[:10]


async def screen_biotech_turnaround(
    db: "AsyncSession",
    limit: int = 12,
    min_score: int = 0,
) -> ScreenerRun:
    from services.market_data import (
        fetch_and_store_fundamentals,
        fetch_and_store_news,
        fetch_and_store_prices,
    )

    universe = load_biotech_universe()

    # Sektor-Regime einmal pro Lauf: in einen Biotech-Abwärtstrend (XBI) kaufen
    # wir keine Turnarounds (vermeidet die sektorweiten Verlustwochen).
    sector_downtrend = False
    try:
        xbi = await fetch_and_store_prices("XBI", db, period="1y")
        xbi_closes = [
            c for c in (
                _to_float(getattr(p, "close", None))
                for p in sorted(xbi, key=lambda p: _as_date(getattr(p, "date")))
            ) if c is not None
        ]
        sector_downtrend = sector_regime(xbi_closes) == "down"
    except Exception:
        sector_downtrend = False

    candidates: list[ScreenerCandidate] = []
    nasdaq_biotech_count = 0
    market_cap_count = 0
    revenue_growth_count = 0
    current_signal_count = 0
    score_count = 0

    for stock in universe:
        is_nasdaq_biotech = (
            stock.exchange.upper() == "NASDAQ"
            and ("biotech" in stock.industry.lower() or "biotechnology" in stock.industry.lower())
        )
        if not is_nasdaq_biotech:
            continue
        nasdaq_biotech_count += 1

        fundamentals = await fetch_and_store_fundamentals(stock.ticker, db)
        if fundamentals is None:
            continue

        market_cap = _to_float(getattr(fundamentals, "market_cap", None))
        revenue_growth = _to_float(getattr(fundamentals, "revenue_growth", None))
        if market_cap is None or market_cap > MAX_MARKET_CAP:
            continue
        market_cap_count += 1

        # Pre-Revenue-Fallback: kein Umsatz (None) ist ok; nur schrumpfender Umsatz (<= 0) fliegt raus.
        if revenue_growth is not None and revenue_growth <= 0:
            continue
        revenue_growth_count += 1

        prices = await fetch_and_store_prices(stock.ticker, db, period="1y")
        news = await fetch_and_store_news(stock.ticker, db, days=TURNAROUND_DAYS)
        insider_buys = await fetch_insider_buys(stock.ticker, days=TURNAROUND_DAYS)
        insider_context_buys = await fetch_insider_buys(stock.ticker, days=INSIDER_CONTEXT_DAYS)

        alt_a = score_alt_a(prices)
        alt_b = score_alt_b(fundamentals, prices, news, insider_buys, ticker=stock.ticker,
                            name=stock.name, sector_downtrend=sector_downtrend)
        if not has_current_turnaround_signal(alt_b):
            continue
        current_signal_count += 1
        if alt_b.score < min_score:
            continue
        score_count += 1

        candidates.append(ScreenerCandidate(
            ticker=stock.ticker,
            name=stock.name,
            exchange=stock.exchange,
            industry=stock.industry,
            market_cap=market_cap,
            revenue_growth=revenue_growth,
            performance_90d=alt_b.performance_90d,
            alt_a=alt_a,
            alt_b=alt_b,
            turnaround_news=alt_b.turnaround_news,
            insider_buys=insider_buys,
            insider_context_buys=insider_context_buys,
            biotech_events=alt_b.biotech_events,
            risk_flags=alt_b.agent_analysis.risks if alt_b.agent_analysis else [],
        ))

    candidates.sort(key=lambda c: (c.alt_b.score, c.alt_a.score), reverse=True)
    limited = candidates[:limit]
    return ScreenerRun(
        universe_count=len(universe),
        filter_funnel=[
            ScreenerFunnelStep("Universum", len(universe), "kuratiertes NASDAQ-Biotech-Startuniversum"),
            ScreenerFunnelStep("NASDAQ Biotech", nasdaq_biotech_count, "Exchange und Sektor passen"),
            ScreenerFunnelStep("Market Cap <= 15 Mrd.", market_cap_count, "Mid-Cap/Small-Cap-Grenze erfüllt"),
            ScreenerFunnelStep("Umsatzwachstum > 0", revenue_growth_count, "operative Verbesserung im letzten Quartal"),
            ScreenerFunnelStep("7-Tage-Signal", current_signal_count, "aktuelle News oder qualifizierter Insider-Kauf"),
            ScreenerFunnelStep("Score-Filter", score_count, f"Score >= {min_score}, danach Limit {limit}"),
        ],
        windows=ScreenerWindows(),
        candidates=limited,
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return _as_date(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _stddev(values: list[float]) -> float:
    avg = _mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _alt_a_label(score: int) -> str:
    if score >= 70:
        return "Technisch positiv"
    if score >= 35:
        return "Technisch neutral"
    return "Technisch schwach"
