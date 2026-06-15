"""Alt-B turnaround scoring — pure, dependency-light, unit-testable core.

Given already-fetched fundamentals, prices, news and insider buys, this produces a
deterministic ``StrategyScore`` (gate + confidence tiers + decision log). It performs
**no I/O** — fetching/persistence lives in ``screener.py``; event classification and
the weakness/setup signal come from ``event_strength.py``.

Schicht 1 (ADR-13) is purely deterministic regex. The hybrid NL layer (Schicht 2–4,
ADR-14) plugs in via ``nl_target.py`` and feeds the catalyst strength used below.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from services.event_strength import classify_event, is_relevant, setup_signal
from services.trace import Trace
from services.screening_types import (
    CONTEXT_DAYS,
    MIN_INSIDER_VALUE,
    AgentAnalysis,
    InsiderBuy,
    ScoreBreakdown,
    StrategyScore,
    _as_date,
    _to_float,
)

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

    # Structured decision trace — one step per scoring stage + the gate (see services/trace.py).
    tr = Trace()
    for b in score_breakdown:
        tr.add(b.label, status="ok" if b.passed else "skip", reason=b.detail,
               points=b.points, max_points=b.max_points)
    if qualifies:
        gate_reason = "Gate erfüllt: Schwäche-Setup UND Katalysator >= 3, Sektor nicht im Abwärtstrend."
    elif gate_signal and sector_downtrend:
        gate_reason = "Gate blockiert: Biotech-Sektor (XBI) im Abwärtstrend."
    elif best is not None and not setup.is_setup:
        gate_reason = "Gate nicht erfüllt: Katalysator vorhanden, aber kein Schwäche-Setup."
    elif setup.is_setup and best is None:
        gate_reason = "Gate nicht erfüllt: Schwäche-Setup, aber kein starker Katalysator (>= 3)."
    else:
        gate_reason = "Gate nicht erfüllt: weder Schwäche-Setup noch starker Katalysator."
    tr.add("gate", status="ok" if qualifies else "skip", reason=gate_reason,
           qualifies=qualifies, score=score, label=label)

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
        trace=tr.steps,
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
