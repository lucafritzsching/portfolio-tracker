"""Deterministic screener strategies for NASDAQ biotech candidates.

The screener searches a small curated universe first. That keeps demos stable and
avoids turning the app into a rate-limit-heavy full-market crawler.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx

from services.event_strength import classify_event, is_relevant, sector_regime, setup_signal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_MARKET_CAP = 15_000_000_000
TURNAROUND_DAYS = 7
CONTEXT_DAYS = 90
INSIDER_CONTEXT_DAYS = 180
MIN_INSIDER_VALUE = 50_000

_TURNAROUND_KEYWORDS = (
    "phase 2",
    "phase 3",
    "clinical",
    "trial",
    "positive data",
    "fda",
    "fast track",
    "breakthrough",
    "orphan",
    "approval",
    "approved",
    "cleared",
    "regulatory",
    "partnership",
    "collaboration",
    "cooperation",
    "license",
    "financing",
    "cash runway",
    "strategic",
    "restructuring",
    "guidance",
    "forecast",
    "outlook",
    "analyst",
    "upgrade",
    "price target",
    "new product",
    "launch",
    "milestone",
)

_RISK_KEYWORDS = (
    "risk",
    "delay",
    "delayed",
    "halt",
    "hold",
    "rejection",
    "reject",
    "warning",
    "miss",
    "decline",
    "drop",
    "lawsuit",
    "investigation",
    "dilution",
    "offering",
    "cash burn",
    "layoff",
    "cuts",
)

_BIOTECH_EVENT_RULES = (
    ("FDA/Regulatorik", ("fda", "fast track", "breakthrough", "orphan", "approval", "approved", "cleared", "regulatory", "ind", "pdufa")),
    ("Studiendaten", ("phase 1", "phase 2", "phase 3", "clinical", "trial", "positive data", "preclinical", "efficacy")),
    ("Partnerschaft", ("partnership", "collaboration", "cooperation", "license", "strategic alliance")),
    ("Prognose/Restrukturierung", ("guidance", "forecast", "outlook", "restructuring", "strategic review")),
    ("Analysten/Finanzierung", ("analyst", "upgrade", "price target", "financing", "cash runway")),
)


@dataclass(frozen=True)
class ScreenerStock:
    ticker: str
    name: str
    exchange: str
    industry: str


@dataclass(frozen=True)
class InsiderBuy:
    name: str
    transaction_date: date | None
    filing_date: date | None
    shares: float
    price: float | None = None

    @property
    def value(self) -> float | None:
        if self.price is None:
            return None
        return round(self.shares * self.price, 2)


@dataclass
class ScoreBreakdown:
    label: str
    points: int
    max_points: int
    passed: bool
    detail: str


@dataclass
class AgentAnalysis:
    turnaround_story: bool
    positive_events: list[str]
    risks: list[str]
    signal_quality: list[str]
    why_interesting: str


@dataclass
class StrategyScore:
    strategy: str
    score: int
    label: str
    reasons: list[str]
    evidence: list[str]
    performance_90d: float | None = None
    turnaround_news: list[str] = field(default_factory=list)
    score_breakdown: list[ScoreBreakdown] = field(default_factory=list)
    decision_log: list[str] = field(default_factory=list)
    qualifies: bool = False
    agent_analysis: AgentAnalysis | None = None
    biotech_events: list[str] = field(default_factory=list)


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


def performance_pct(prices: list[Any], days: int = CONTEXT_DAYS) -> float | None:
    rows = sorted(
        [p for p in prices if getattr(p, "date", None) is not None and getattr(p, "close", None) is not None],
        key=lambda p: _as_date(getattr(p, "date")),
    )
    if len(rows) < 2:
        return None

    latest = rows[-1]
    latest_date = _as_date(getattr(latest, "date"))
    target = latest_date - timedelta(days=days)
    lookback = [p for p in rows if _as_date(getattr(p, "date")) <= target]
    base = lookback[-1] if lookback else rows[0]
    base_close = _to_float(getattr(base, "close", None))
    latest_close = _to_float(getattr(latest, "close", None))
    if not base_close or latest_close is None:
        return None
    return round((latest_close - base_close) / base_close, 4)


def turnaround_headlines(news: list[Any], limit: int = 3) -> list[str]:
    hits: list[str] = []
    for item in news:
        headline = str(getattr(item, "headline", "") or "").strip()
        summary = str(getattr(item, "summary", "") or "")
        text = f"{headline} {summary}".lower()
        sentiment = _to_float(getattr(item, "sentiment", None))
        if headline and (any(key in text for key in _TURNAROUND_KEYWORDS) or (sentiment is not None and sentiment > 0.25)):
            hits.append(headline)
        if len(hits) >= limit:
            break
    return hits


def biotech_event_tags(news: list[Any], limit: int = 4) -> list[str]:
    tags: list[str] = []
    for item in news:
        headline = str(getattr(item, "headline", "") or "")
        summary = str(getattr(item, "summary", "") or "")
        text = f"{headline} {summary}".lower()
        for label, keywords in _BIOTECH_EVENT_RULES:
            if label not in tags and any(keyword in text for keyword in keywords):
                tags.append(label)
                if len(tags) >= limit:
                    return tags
    return tags


def risk_headlines(news: list[Any], limit: int = 3) -> list[str]:
    risks: list[str] = []
    for item in news:
        headline = str(getattr(item, "headline", "") or "").strip()
        summary = str(getattr(item, "summary", "") or "")
        text = f"{headline} {summary}".lower()
        if headline and any(key in text for key in _RISK_KEYWORDS):
            risks.append(headline)
        if len(risks) >= limit:
            break
    return risks


def qualified_insider_buys(
    insider_buys: list[InsiderBuy],
    min_value: float = MIN_INSIDER_VALUE,
) -> list[InsiderBuy]:
    return [
        buy
        for buy in insider_buys
        if buy.value is not None and buy.value >= min_value
    ]


def insider_quality_detail(insider_buys: list[InsiderBuy]) -> str:
    qualified = qualified_insider_buys(insider_buys)
    if not insider_buys:
        return "Keine Form-4/Finnhub-Open-Market-Käufe in den letzten 7 Tagen."
    if not qualified:
        return f"{len(insider_buys)} Kauf/Käufe gefunden, aber unter Mindestwert ${MIN_INSIDER_VALUE:,.0f}."

    total = sum(buy.value or 0 for buy in qualified)
    names = ", ".join(buy.name for buy in qualified[:2])
    if len(qualified) >= 2 or total >= 250_000:
        label = "Starke Insider-Bestätigung"
    else:
        label = "Qualifizierter Insider-Kauf"
    return f"{label}: {len(qualified)} Kauf/Käufe, ca. ${total:,.0f}, {names}."


def score_alt_b(
    fundamentals: Any,
    prices: list[Any],
    news: list[Any],
    insider_buys: list[InsiderBuy],
    ticker: str = "",
    name: str = "",
    sector_downtrend: bool = False,
) -> StrategyScore:
    """Event-basierter Turnaround-Score mit Gate + Konfidenz-Stufen.

    Pflicht-Gate: Schwäche-Setup UND ein echter Katalysator (Stärke >= 3, positiv,
    ticker-relevant), und der Biotech-Sektor darf nicht im Abwärtstrend sein.
    Insider/Wachstum heben danach die Stufe. Schwache News (Stärke <= 2) und reines
    Momentum (kein Setup) qualifizieren bewusst NICHT.
    """
    reasons: list[str] = []
    evidence: list[str] = []
    score_breakdown: list[ScoreBreakdown] = []
    decision_log: list[str] = []
    perf_90d = performance_pct(prices, CONTEXT_DAYS)
    biotech_events = biotech_event_tags(news)
    qualified_buys = qualified_insider_buys(insider_buys)
    revenue_growth = _to_float(getattr(fundamentals, "revenue_growth", None))
    market_cap = _to_float(getattr(fundamentals, "market_cap", None))

    # ── Schwäche-Setup (Teil des Gates) ──
    closes = [
        c for c in (
            _to_float(getattr(p, "close", None))
            for p in sorted(prices, key=lambda p: _as_date(getattr(p, "date")))
        ) if c is not None
    ]
    setup = setup_signal(closes)

    # ── Ereignis-Klassifikation: nur ticker-relevante, positive News ──
    classified: list[tuple[str, Any]] = []
    for item in news:
        headline = str(getattr(item, "headline", "") or "")
        summary = str(getattr(item, "summary", "") or "")
        if not headline or not is_relevant(headline, summary, ticker, name):
            continue
        ev = classify_event(headline, summary, getattr(item, "source", None))
        classified.append((headline, ev))
    qualifying = [(h, ev) for h, ev in classified if ev.qualifies]
    best = max(qualifying, key=lambda t: t[1].strength, default=None)
    positives = [(h, ev) for h, ev in classified if ev.direction == "positive"]
    best_any = max(positives, key=lambda t: t[1].strength, default=None)
    news_hits = [h for h, _ in qualifying]

    agent_analysis = analyze_news_agent(
        news=news,
        turnaround_news=news_hits,
        insider_buys=qualified_buys,
        revenue_growth=revenue_growth,
        performance_90d=perf_90d,
        biotech_events=biotech_events,
    )

    if market_cap is not None:
        decision_log.append(f"Basisfilter bestanden: NASDAQ, Biotech, Market Cap ${market_cap:,.0f} <= $15 Mrd.")
    else:
        decision_log.append("Basisfilter bestanden: NASDAQ, Biotech, Market Cap <= $15 Mrd.")

    # ── Katalysator-Stärke (bis 40 Punkte, nur bei Stärke >= 3) ──
    event_points = round(best[1].strength / 5 * 40) if best else 0
    if best:
        h, ev = best
        reasons.append(f"Echter Turnaround-Katalysator (Stärke {ev.strength}/5): {ev.type}")
        evidence.extend(news_hits[:3])
        decision_log.append(f"Katalysator Stärke {ev.strength}/5 erkannt ({ev.type}): {h}")
        catalyst_detail = f"Stärke {ev.strength}/5 – {ev.type}: {h}"
    elif best_any:
        h, ev = best_any
        cap = " (Quelle gedeckelt → Recap)" if ev.capped_by_source else ""
        decision_log.append(f"News erkannt, aber nur Stärke {ev.strength}/5{cap} → kein Turnaround-Signal: {h}")
        catalyst_detail = f"Nur Stärke {ev.strength}/5{cap} – zählt nicht (Schwelle: 3)."
    else:
        decision_log.append("Kein relevanter positiver Katalysator in den letzten 7 Tagen.")
        catalyst_detail = "Kein relevanter positiver Katalysator erkannt."
    score_breakdown.append(ScoreBreakdown(
        label="Turnaround-Katalysator",
        points=event_points,
        max_points=40,
        passed=best is not None,
        detail=catalyst_detail,
    ))

    # ── Insider-Qualität (bis 30) ──
    insider_points = 30 if qualified_buys else 0
    if qualified_buys:
        total = sum(b.value or 0 for b in qualified_buys)
        evidence.append(f"Insider-Käufe: ${total:,.0f}")
        reasons.append("Qualifizierter Insider-Kauf in den letzten 7 Tagen")
        decision_log.append(f"Qualifizierter Insider-Kauf: {len(qualified_buys)} Kauf/Käufe, ca. ${total:,.0f}.")
    elif insider_buys:
        decision_log.append(f"Insider-Kauf gefunden, aber unter Mindestwert ${MIN_INSIDER_VALUE:,.0f}.")
    else:
        decision_log.append("Kein qualifizierter Insider-Kauf in den letzten 7 Tagen.")
    score_breakdown.append(ScoreBreakdown(
        label="Insider-Qualität", points=insider_points, max_points=30,
        passed=bool(qualified_buys), detail=insider_quality_detail(insider_buys),
    ))

    # ── Umsatzwachstum (bis 20) ──
    growth_points = 0
    if revenue_growth is not None and revenue_growth > 0.05:
        growth_points = 20
        reasons.append("Umsatzwachstum über 5%")
        decision_log.append(f"Umsatzwachstum stark positiv: {revenue_growth * 100:.1f}% (> 5%).")
    elif revenue_growth is not None and revenue_growth > 0:
        growth_points = 10
        decision_log.append(f"Umsatzwachstum positiv: {revenue_growth * 100:.1f}% (> 0%).")
    else:
        decision_log.append("Kein positives Umsatzwachstum im letzten Quartal erkannt.")
    score_breakdown.append(ScoreBreakdown(
        label="Umsatzwachstum", points=growth_points, max_points=20, passed=growth_points > 0,
        detail=(f"{revenue_growth * 100:.1f}% Umsatzwachstum." if revenue_growth is not None
                else "Keine Umsatzwachstumsdaten verfügbar."),
    ))

    # ── Schwäche-Setup (bis 10, Teil des Gates) ──
    setup_points = 10 if setup.is_setup else 0
    if setup.is_setup:
        reasons.append("Turnaround-Setup: ausgebombt + überverkauft")
    decision_log.append(setup.reason)
    score_breakdown.append(ScoreBreakdown(
        label="Turnaround-Setup", points=setup_points, max_points=10,
        passed=setup.is_setup, detail=setup.reason,
    ))

    score = min(event_points + insider_points + growth_points + setup_points, 100)

    # ── Das Gate: echter Turnaround = Schwäche-Setup UND starker Katalysator,
    #    und der Biotech-Sektor darf nicht im Abwärtstrend sein. ──
    gate_signal = setup.is_setup and best is not None
    qualifies = gate_signal and not sector_downtrend
    if gate_signal and sector_downtrend:
        decision_log.append("Sektor-Regime: Biotech-Index (XBI) im Abwärtstrend → kein Einstieg trotz Signal.")
    elif not gate_signal:
        if best is not None and not setup.is_setup:
            decision_log.append("Gate NICHT erfüllt: starker Katalysator, aber kein Schwäche-Setup (nicht ausgebombt / schon gelaufen).")
        elif setup.is_setup and best is None:
            decision_log.append("Gate NICHT erfüllt: ausgebombt, aber kein starker Katalysator (Stärke >= 3).")
        else:
            decision_log.append("Gate NICHT erfüllt: weder Schwäche-Setup noch starker Katalysator.")

    label = _alt_b_tier(qualifies, bool(qualified_buys), revenue_growth)
    if biotech_events:
        decision_log.append(f"Biotech-Signaltypen erkannt: {', '.join(biotech_events)}.")
    decision_log.append(f"Gesamtergebnis: {score}/100 Punkte, Einstufung: {label}.")
    return StrategyScore(
        strategy="ALT_B",
        score=score,
        label=label,
        reasons=reasons,
        evidence=evidence,
        performance_90d=perf_90d,
        turnaround_news=news_hits,
        score_breakdown=score_breakdown,
        decision_log=decision_log,
        qualifies=qualifies,
        agent_analysis=agent_analysis,
        biotech_events=biotech_events,
    )


def has_current_turnaround_signal(score: StrategyScore) -> bool:
    return score.qualifies


def analyze_news_agent(
    news: list[Any],
    turnaround_news: list[str],
    insider_buys: list[InsiderBuy],
    revenue_growth: float | None,
    performance_90d: float | None,
    biotech_events: list[str] | None = None,
) -> AgentAnalysis:
    positive_events = list(turnaround_news)
    if insider_buys:
        total = sum(b.value or 0 for b in insider_buys)
        if total:
            positive_events.append(f"Insider-Käufe der letzten 7 Tage im Wert von ca. ${total:,.0f}.")
        else:
            positive_events.append(f"{len(insider_buys)} Insider-Kauf/Käufe in den letzten 7 Tagen.")

    risks = risk_headlines(news)
    signal_quality = list(biotech_events or [])

    reasons: list[str] = []
    if revenue_growth is not None and revenue_growth > 0:
        reasons.append(f"positives Umsatzwachstum von {revenue_growth * 100:.1f}%")
    if turnaround_news:
        reasons.append("aktueller News-Katalysator")
    if insider_buys:
        reasons.append("qualifiziertes Insider-Bestätigungssignal")
    if signal_quality:
        reasons.append("biotech-spezifische Signalqualität: " + ", ".join(signal_quality))
    if performance_90d is not None and performance_90d <= -0.20:
        reasons.append(f"Turnaround-Kontext nach {performance_90d * 100:.1f}% in 90 Tagen")

    if reasons:
        why = "Interessant, weil " + ", ".join(reasons) + "."
    else:
        why = "Noch keine aktuelle Turnaround-Story nach den definierten Alt-B-Kriterien."

    return AgentAnalysis(
        turnaround_story=bool(positive_events),
        positive_events=positive_events,
        risks=risks,
        signal_quality=signal_quality,
        why_interesting=why,
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


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


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


def _alt_b_label(score: int) -> str:
    if score >= 75:
        return "Starker Turnaround-Kandidat"
    if score >= 50:
        return "Watchlist Turnaround"
    return "Noch kein Turnaround-Signal"


def _alt_b_tier(qualifies: bool, has_insider: bool, revenue_growth: float | None) -> str:
    """Ehrliche Einstufung: erst durchs Gate, dann Konfidenz-Stufe je nach Bestätigung."""
    if not qualifies:
        return "Kein Alt-B-Signal"
    strong_growth = revenue_growth is not None and revenue_growth > 0.05
    if has_insider and strong_growth:
        return "Top-Treffer"
    if has_insider:
        return "Hohe Konviktion"
    return "Watchlist Turnaround"
