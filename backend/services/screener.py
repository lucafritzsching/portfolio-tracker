"""Alt-B-Screener: NASDAQ-Biotech-Turnarounds (Schicht 2).

Gestufter Scan über das gecachte Universum (Button + SSE + DB-Cache statt Live-GET):
billige Filter zuerst (Fundamentals, EDGAR-Vorprüfung mit einem submissions-Call),
teure Schritte (Finnhub-News/-Insider, 8-K-Pressetexte, LLM) nur für die Treffer.
Ohne gecachtes Universum liefert der Scan ein leeres Ergebnis; Aufbau per Refresh-Button.
"""
from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING

import httpx

from services.event_llm import LLMEvent, classify_event_llm
from services.event_strength import EventClassification, classify_event, is_relevant
from services.sec_filings import (
    Filing8K,
    fetch_8k_catalysts,
    fetch_cik_map,
    fetch_recent_signals,
)
from services.screener_research import (
    ResearchBrief,
    aggregate_insider_context,
    build_event_timeline,
    build_research_brief,
    detect_risk_signals,
    detect_upcoming_catalysts,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from schemas import ScreenerCandidateOut, ScreenerResponseOut

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
    story_de: str = ""
    evidence_quote: str = ""
    used_llm: bool = False
    event_type: str = ""
    event_strength: int = 0
    event_evidence: str = ""


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
    sec_filings: list[Filing8K] = field(default_factory=list)
    research: ResearchBrief = field(default_factory=ResearchBrief)


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
    # Pre-Revenue-Fallback (ADR-13): kein Umsatz = ok, nur schrumpfender Umsatz fällt raus.
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
    llm_event: LLMEvent | None = None,
    sec_events: list[tuple[Filing8K, EventClassification]] | None = None,
) -> StrategyScore:
    """Originale Alt-B-Strategie: Basisfilter plus Event- oder Insider-Signal.

    Der Score bewertet nur die Alt-B-Idee aus dem Projektplan:
    starker Unternehmens-Katalysator der letzten 7 Tage (Stärke >= 3) ODER
    qualifizierter Insider-Kauf. Ein Kurs-Setup ist bewusst kein Gate.

    Katalysator-Quellen: regex-klassifizierte News, regex-klassifizierte 8-K-Pressetexte
    (`sec_events`) und — wenn vorhanden — die LLM-Klassifikation (`llm_event`), deren
    Stärke deterministisch aus der Rubrik kommt. Die stärkste qualifizierende gewinnt.
    """
    reasons: list[str] = []
    evidence: list[str] = []
    score_breakdown: list[ScoreBreakdown] = []
    decision_log: list[str] = []
    perf_90d = performance_pct(prices, CONTEXT_DAYS)
    qualified_buys = qualified_insider_buys(insider_buys)
    revenue_growth = _to_float(getattr(fundamentals, "revenue_growth", None))
    market_cap = _to_float(getattr(fundamentals, "market_cap", None))

    # ── Ereignis-Klassifikation: nur ticker-relevante, positive News zählen ──
    classified: list[tuple[str, Any, Any]] = []
    for item in news:
        headline = str(getattr(item, "headline", "") or "")
        summary = str(getattr(item, "summary", "") or "")
        if not headline or not is_relevant(headline, summary, ticker, name):
            continue
        ev = classify_event(headline, summary, getattr(item, "source", None))
        classified.append((headline, ev, item))
    for filing, ev in sec_events or []:
        label = f"8-K {filing.filing_date}: {filing.event_type}"
        classified.append((label, ev, None))
    if llm_event is not None and llm_event.used_llm:
        label = llm_event.evidence_quote or llm_event.story_de or "LLM-Klassifikation"
        classified.append((label, llm_event.classification, None))
    qualifying = [(h, ev, item) for h, ev, item in classified if ev.qualifies]
    best = max(qualifying, key=lambda t: t[1].strength, default=None)
    observed_events = [
        (h, ev, item)
        for h, ev, item in classified
        if ev.direction != "negative" and ev.strength > 0
    ]
    best_any = max(observed_events, key=lambda t: t[1].strength, default=None)
    news_hits = [h for h, _, _ in qualifying]
    biotech_events = biotech_event_tags([item for _, _, item in qualifying if item is not None])
    event_type = best[1].type if best else ""
    event_strength = best[1].strength if best else 0
    event_evidence = best[0] if best else ""

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

    # ── Katalysator-Stärke (bis 50 Punkte, nur bei Stärke >= 3) ──
    event_points = {5: 50, 4: 40, 3: 30}.get(best[1].strength, 0) if best else 0
    if best:
        h, ev, _ = best
        reasons.append(f"Echter Turnaround-Katalysator (Stärke {ev.strength}/5): {ev.type}")
        evidence.extend(news_hits[:3])
        decision_log.append(f"Katalysator Stärke {ev.strength}/5 erkannt ({ev.type}): {h}")
        catalyst_detail = f"Stärke {ev.strength}/5 – {ev.type}: {h}"
    elif best_any:
        h, ev, _ = best_any
        cap = " (Quelle gedeckelt → Recap)" if ev.capped_by_source else ""
        decision_log.append(f"News erkannt, aber nur Stärke {ev.strength}/5{cap} → kein Turnaround-Signal: {h}")
        catalyst_detail = f"Nur Stärke {ev.strength}/5{cap} – zählt nicht (Schwelle: 3)."
    else:
        decision_log.append("Kein starkes Turnaround-Event in den letzten 7 Tagen erkannt.")
        catalyst_detail = "Kein starkes Turnaround-Event erkannt."
    score_breakdown.append(ScoreBreakdown(
        label="Turnaround-Katalysator",
        points=event_points,
        max_points=50,
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

    # ── Umsatzwachstum (Bonus, bis 20 — Pre-Revenue ist zulässig, gibt nur keine Punkte) ──
    if revenue_growth is not None and revenue_growth > 0:
        growth_points = 20
        reasons.append("Positives Umsatzwachstum im letzten Quartal")
        decision_log.append(f"Umsatzwachstum positiv: {revenue_growth * 100:.1f}% (> 0%).")
    elif revenue_growth is None:
        growth_points = 0
        decision_log.append("Pre-Revenue: keine Umsatzdaten — zulässig, aber keine Bonuspunkte.")
    else:
        growth_points = 0
        decision_log.append("Kein positives Umsatzwachstum im letzten Quartal erkannt.")
    score_breakdown.append(ScoreBreakdown(
        label="Umsatzwachstum", points=growth_points, max_points=20, passed=growth_points > 0,
        detail=(f"{revenue_growth * 100:.1f}% Umsatzwachstum." if revenue_growth is not None
                else "Pre-Revenue: keine Umsatzdaten (zulässig)."),
    ))

    score = min(event_points + insider_points + growth_points, 100)
    has_catalyst = best is not None
    qualifies = has_catalyst or bool(qualified_buys)
    if qualifies:
        decision_log.append("Alt-B-Gate erfüllt: starkes 7-Tage-Event oder qualifizierter Insider-Kauf vorhanden.")
    else:
        decision_log.append("Alt-B-Gate nicht erfüllt: weder starkes 7-Tage-Event noch qualifizierter Insider-Kauf.")

    used_llm = llm_event is not None and llm_event.used_llm
    if used_llm:
        decision_log.append(f"LLM-Klassifikation aktiv: Typ \"{llm_event.classification.type}\" (Stärke aus Rubrik).")
    elif llm_event is not None:
        decision_log.append("LLM nicht verfügbar/verworfen — Regex-Klassifikation als Fallback.")

    label = _alt_b_label(score, qualifies)
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
        story_de=llm_event.story_de if used_llm else "",
        evidence_quote=llm_event.evidence_quote if used_llm else "",
        used_llm=used_llm,
        event_type=event_type,
        event_strength=event_strength,
        event_evidence=event_evidence,
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


# ── Schicht-2-Scan: Universum → billige Filter → EDGAR-Vorprüfung → Detail + LLM ──

ProgressFn = Callable[[dict], Awaitable[None]]


def build_event_material(
    sec_events: list[tuple[Filing8K, EventClassification]],
    news: list[Any],
    ticker: str,
    name: str,
    max_headlines: int = 5,
) -> str:
    """Rohmaterial für die LLM-Klassifikation: 8-K-Pressetexte + relevante Headlines."""
    parts: list[str] = []
    for filing, _ in sec_events[:2]:
        if filing.press_release:
            parts.append(f"SEC 8-K vom {filing.filing_date}: {filing.press_release}")
    count = 0
    for item in news:
        headline = str(getattr(item, "headline", "") or "")
        summary = str(getattr(item, "summary", "") or "")
        if not headline or not is_relevant(headline, summary, ticker, name):
            continue
        parts.append(f"News: {headline}. {summary}".strip())
        count += 1
        if count >= max_headlines:
            break
    return "\n\n".join(parts)


async def run_alt_b_scan(
    db: "AsyncSession",
    limit: int = 12,
    min_score: int = 0,
    progress: ProgressFn | None = None,
) -> ScreenerResponseOut:
    """Gestufter Scan über das gecachte Universum; Ergebnis wird in screener_runs persistiert."""
    from schemas import ScreenerFunnelStepOut, ScreenerResponseOut, ScreenerWindowsOut
    from services.market_data import (
        fetch_and_store_fundamentals,
        fetch_and_store_news,
        fetch_and_store_prices,
    )
    from services.universe import load_universe

    async def emit(event: dict) -> None:
        if progress is not None:
            await progress(event)

    uni_stocks, uni_updated = await load_universe(db)
    if uni_stocks:
        # (Stock, grober Market Cap aus dem NASDAQ-Screener — Feinprüfung später via Fundamentals)
        entries = [(ScreenerStock(s.ticker, s.name, "NASDAQ", s.industry), s.market_cap) for s in uni_stocks]
    else:
        entries = []
    universe_source = "live"

    today = datetime.utcnow().date()
    window_from = (today - timedelta(days=TURNAROUND_DAYS)).isoformat()
    window_to = today.isoformat()

    # Stufe 1: grober Cap-Vorfilter aus den Screener-Daten (unbekannter Cap bleibt drin,
    # die verbindliche Prüfung macht später der Fundamentals-Recheck).
    cap_pass = [(stock, cap) for stock, cap in entries if cap is None or cap <= MAX_MARKET_CAP]

    candidates: list[ScreenerCandidate] = []
    edgar_pass: list[tuple[ScreenerStock, int, bool]] = []
    base_count = 0
    signal_count = 0
    score_count = 0

    async with httpx.AsyncClient(timeout=30) as client:
        # Stufe 2: EDGAR-Vorprüfung — EIN submissions-Call je Ticker (8-K + Form 4 zugleich).
        # Läuft VOR den Fundamentals: gratis und ohne Rate-Limit-Druck, dadurch braucht
        # yfinance/Finnhub nur noch die wenigen Signal-Ticker.
        cik_map = await fetch_cik_map(client) if cap_pass else {}
        for i, (stock, _cap) in enumerate(cap_pass):
            await emit({"stage": "EDGAR-Vorprüfung", "i": i + 1, "n": len(cap_pass), "ticker": stock.ticker})
            cik = cik_map.get(stock.ticker)
            if cik is None:
                continue
            has_8k, has_form4 = await fetch_recent_signals(client, stock.ticker, cik, window_from, window_to)
            await asyncio.sleep(0.15)  # SEC erlaubt ~10 req/s — bewusst defensiv
            if has_8k or has_form4:
                edgar_pass.append((stock, cik, has_8k))

        # Stufe 3+4: Fundamentals-Recheck + Detail (Finnhub/yfinance/8-K-Pressetexte) + LLM.
        for i, (stock, cik, has_8k) in enumerate(edgar_pass):
            await emit({"stage": "Detail + LLM", "i": i + 1, "n": len(edgar_pass), "ticker": stock.ticker})
            fundamentals = await fetch_and_store_fundamentals(stock.ticker, db)
            if fundamentals is None:
                continue
            market_cap = _to_float(getattr(fundamentals, "market_cap", None))
            if market_cap is None or market_cap > MAX_MARKET_CAP:
                continue
            revenue_growth = _to_float(getattr(fundamentals, "revenue_growth", None))
            if revenue_growth is not None and revenue_growth <= 0:
                continue
            base_count += 1

            prices = await fetch_and_store_prices(stock.ticker, db, period="1y")
            news = await fetch_and_store_news(stock.ticker, db, days=TURNAROUND_DAYS)
            insider_buys = await fetch_insider_buys(stock.ticker, days=TURNAROUND_DAYS)
            insider_context_buys = await fetch_insider_buys(stock.ticker, days=INSIDER_CONTEXT_DAYS)
            sec_events = (
                await fetch_8k_catalysts(client, stock.ticker, cik, window_from, window_to)
                if has_8k else []
            )

            material = build_event_material(sec_events, news, stock.ticker, stock.name)
            llm_event = await classify_event_llm(material, stock.ticker, stock.name) if material else None

            alt_a = score_alt_a(prices)
            alt_b = score_alt_b(
                fundamentals, prices, news, insider_buys,
                ticker=stock.ticker, name=stock.name,
                llm_event=llm_event, sec_events=sec_events,
            )
            if not has_current_turnaround_signal(alt_b):
                continue
            signal_count += 1
            if alt_b.score < min_score:
                continue
            score_count += 1
            insider_context = aggregate_insider_context(insider_buys, insider_context_buys)
            event_timeline = build_event_timeline(news, sec_events, stock.ticker, stock.name)
            risk_signals = detect_risk_signals(news)
            upcoming_catalysts = detect_upcoming_catalysts(news)
            research = build_research_brief(
                revenue_growth=revenue_growth,
                insider_context=insider_context,
                event_timeline=event_timeline,
                risk_signals=risk_signals,
                upcoming_catalysts=upcoming_catalysts,
            )

            candidates.append(ScreenerCandidate(
                ticker=stock.ticker,
                name=stock.name,
                exchange=stock.exchange,
                industry=stock.industry,
                market_cap=_to_float(getattr(fundamentals, "market_cap", None)),
                revenue_growth=_to_float(getattr(fundamentals, "revenue_growth", None)),
                performance_90d=alt_b.performance_90d,
                alt_a=alt_a,
                alt_b=alt_b,
                turnaround_news=alt_b.turnaround_news,
                insider_buys=insider_buys,
                insider_context_buys=insider_context_buys,
                biotech_events=alt_b.biotech_events,
                risk_flags=[signal.label for signal in risk_signals] or (alt_b.agent_analysis.risks if alt_b.agent_analysis else []),
                sec_filings=[filing for filing, _ in sec_events],
                research=research,
            ))

    candidates.sort(key=lambda c: (c.alt_b.score, c.alt_a.score), reverse=True)
    universe_detail = (
        f"gecrawltes NASDAQ-Biotech-Universum (Stand {uni_updated:%d.%m.%Y})"
        if universe_source == "live" and uni_updated
        else "kein gecachtes Universum — bitte Universum aktualisieren"
    )
    response = ScreenerResponseOut(
        universe_count=len(entries),
        filter_funnel=[
            ScreenerFunnelStepOut(label="Universum", count=len(entries), detail=universe_detail),
            ScreenerFunnelStepOut(label="Market Cap <= 15 Mrd.", count=len(cap_pass),
                                  detail="Screener-Vorfilter; verbindlicher Recheck via Fundamentals"),
            ScreenerFunnelStepOut(label="EDGAR-Vorprüfung", count=len(edgar_pass),
                                  detail="8-K-Katalysator oder Form 4 in den letzten 7 Tagen"),
            ScreenerFunnelStepOut(label="Umsatz ok (inkl. Pre-Revenue)", count=base_count,
                                  detail="Cap-Recheck bestanden; Wachstum > 0 oder Pre-Revenue"),
            ScreenerFunnelStepOut(label="7-Tage-Signal", count=signal_count,
                                  detail="starkes Event (Stärke >= 3) oder qualifizierter Insider-Kauf"),
            ScreenerFunnelStepOut(label="Score-Filter", count=score_count,
                                  detail=f"Score >= {min_score}, danach Limit {limit}"),
        ],
        windows=ScreenerWindowsOut(
            event_days=TURNAROUND_DAYS,
            context_days=CONTEXT_DAYS,
            insider_context_days=INSIDER_CONTEXT_DAYS,
        ),
        candidates=[candidate_out(c) for c in candidates[:limit]],
        created_at=datetime.utcnow(),
        universe_source=universe_source,
        universe_updated_at=uni_updated,
    )
    await save_run(db, response)
    return response


# ── Marshalling (Dataclasses → Pydantic) + Persistenz ───────────────────────────

def candidate_out(candidate: ScreenerCandidate) -> "ScreenerCandidateOut":
    from dataclasses import asdict

    from schemas import (
        ScreenerCandidateOut,
        ScreenerFilingOut,
        ScreenerInsiderBuyOut,
        ScreenerResearchBriefOut,
        ScreenerScoreOut,
    )

    def _buy(buy: InsiderBuy) -> ScreenerInsiderBuyOut:
        return ScreenerInsiderBuyOut(
            name=buy.name, transaction_date=buy.transaction_date, filing_date=buy.filing_date,
            shares=buy.shares, price=buy.price, value=buy.value,
        )

    return ScreenerCandidateOut(
        ticker=candidate.ticker,
        name=candidate.name,
        exchange=candidate.exchange,
        industry=candidate.industry,
        market_cap=candidate.market_cap,
        revenue_growth=candidate.revenue_growth,
        performance_90d=candidate.performance_90d,
        alt_a=ScreenerScoreOut(**asdict(candidate.alt_a)),
        alt_b=ScreenerScoreOut(**asdict(candidate.alt_b)),
        turnaround_news=candidate.turnaround_news,
        insider_buys=[_buy(b) for b in candidate.insider_buys],
        insider_context_buys=[_buy(b) for b in candidate.insider_context_buys],
        biotech_events=candidate.biotech_events,
        risk_flags=candidate.risk_flags,
        sec_filings=[
            ScreenerFilingOut(filing_date=f.filing_date, event_type=f.event_type, url=f.url)
            for f in candidate.sec_filings
        ],
        research=ScreenerResearchBriefOut(**asdict(candidate.research)),
    )


async def save_run(db: "AsyncSession", response: ScreenerResponseOut) -> None:
    from models import ScreenerRun as ScreenerRunModel

    db.add(ScreenerRunModel(
        status="completed",
        universe_count=response.universe_count,
        payload=response.model_dump(mode="json"),
    ))
    await db.commit()


async def load_latest_run(db: "AsyncSession") -> "ScreenerResponseOut | None":
    from sqlalchemy import select

    from models import ScreenerRun as ScreenerRunModel
    from schemas import ScreenerResponseOut

    row = (
        await db.execute(
            select(ScreenerRunModel).order_by(ScreenerRunModel.created_at.desc()).limit(1)
        )
    ).scalars().first()
    if row is None:
        return None
    return ScreenerResponseOut.model_validate(row.payload)


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


def _alt_b_label(score: int, qualifies: bool) -> str:
    if not qualifies:
        return "Kein Alt-B-Signal"
    if score >= 80:
        return "Starker Turnaround-Kandidat"
    if score >= 50:
        return "Watchlist Turnaround"
    return "Watchlist Turnaround"
