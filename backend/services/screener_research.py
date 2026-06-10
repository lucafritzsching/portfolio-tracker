"""Evidence-bound research helpers for Alt-B candidates.

This module does not fetch data and does not change the Alt-B gate. It only turns
already collected news, 8-Ks, fundamentals, and insider buys into structured
research fields that can be tested without network access.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from services.event_strength import EventClassification, classify_event, is_relevant


@dataclass
class ResearchPoint:
    text: str
    evidence: str
    evidence_quote: str = ""


@dataclass
class InsiderBuyerSummary:
    name: str
    total_value: float
    buy_count: int


@dataclass
class InsiderContext:
    recent_count: int = 0
    context_count: int = 0
    total_value: float = 0.0
    top_buyers: list[InsiderBuyerSummary] = field(default_factory=list)
    summary: str = "Keine qualifizierten Insider-Käufe in den letzten 7 oder 180 Tagen."


@dataclass
class EventTimelineItem:
    event_date: str
    title: str
    event_type: str
    source: str
    evidence: str
    evidence_quote: str = ""


@dataclass
class RiskSignal:
    label: str
    detail: str
    evidence: str
    evidence_quote: str = ""


@dataclass
class UpcomingCatalyst:
    catalyst_type: str
    date_text: str
    detail: str
    evidence: str
    evidence_quote: str = ""


@dataclass
class ResearchBrief:
    bull_case: list[ResearchPoint] = field(default_factory=list)
    bear_case: list[ResearchPoint] = field(default_factory=list)
    insider_context: InsiderContext = field(default_factory=InsiderContext)
    upcoming_catalysts: list[UpcomingCatalyst] = field(default_factory=list)
    event_timeline: list[EventTimelineItem] = field(default_factory=list)
    risk_signals: list[RiskSignal] = field(default_factory=list)


_RISK_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Shelf Offering", "Shelf Offering kann künftige Verwässerung vorbereiten.", ("shelf offering", "s-3", "shelf registration")),
    ("Verwässerungsrisiko", "Kapitalmaßnahme kann bestehende Aktionäre verwässern.", ("dilut", "public offering", "registered direct", "common stock offering")),
    ("Kapitalerhöhung", "Kapitalerhöhung signalisiert Finanzierungsbedarf.", ("capital raise", "raises capital", "priced offering", "private placement")),
    ("Hoher Cash Burn", "Quelle nennt Cash-Burn- oder Runway-Druck.", ("cash burn", "cash runway", "going concern")),
    ("Negative Studienergebnisse", "Quelle nennt negative oder gescheiterte Studiendaten.", ("failed", "failure", "negative data", "did not meet", "missed primary endpoint")),
    ("FDA-/Studienverzögerung", "Quelle nennt FDA- oder Studienverzögerungen.", ("fda delay", "delayed", "delay", "clinical hold", "study delayed", "trial delayed")),
    ("Hohe Bewertung", "Quelle nennt Bewertungsrisiko.", ("overvalued", "valuation risk", "high valuation")),
)

_CATALYST_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Phase-2 Readout", ("phase 2 readout", "phase ii readout", "phase 2 data", "phase ii data")),
    ("Phase-3 Readout", ("phase 3 readout", "phase iii readout", "phase 3 data", "phase iii data", "pivotal readout")),
    ("FDA-PDUFA-Datum", ("pdufa",)),
    ("ASCO-Präsentation", ("asco",)),
    ("ESMO-Präsentation", ("esmo",)),
    ("Zulassungsentscheidung", ("approval decision", "regulatory decision", "fda decision")),
    ("Management-Event", ("investor day", "r&d day", "management presentation")),
)

_CATALYST_FORWARD_WORDS = ("expects", "expected", "anticipates", "anticipated", "upcoming", "to present", "will present", "readout")


def aggregate_insider_context(
    recent_buys: list[Any],
    context_buys: list[Any],
    window_days: int = 180,
) -> InsiderContext:
    valued = [buy for buy in context_buys if _buy_value(buy) is not None]
    total = round(sum(_buy_value(buy) or 0 for buy in valued), 2)

    grouped: dict[str, dict[str, float]] = {}
    for buy in valued:
        name = str(getattr(buy, "name", None) or "Insider")
        bucket = grouped.setdefault(name, {"total": 0.0, "count": 0.0})
        bucket["total"] += _buy_value(buy) or 0
        bucket["count"] += 1

    top_buyers = [
        InsiderBuyerSummary(name=name, total_value=round(data["total"], 2), buy_count=int(data["count"]))
        for name, data in grouped.items()
    ]
    top_buyers.sort(key=lambda buyer: buyer.total_value, reverse=True)

    recent_count = len(recent_buys)
    context_count = len(context_buys)
    if recent_count:
        summary = (
            f"{recent_count} qualifizierte Insider-Käufe in den letzten 7 Tagen; "
            f"180-Tage-Volumen ca. {_money(total)}."
        )
    elif context_count and total:
        summary = (
            f"Keine Käufe in den letzten 7 Tagen, aber Insider-Käufe über {_money(total)} "
            f"in den letzten {window_days} Tagen."
        )
    else:
        summary = f"Keine qualifizierten Insider-Käufe in den letzten 7 oder {window_days} Tagen."

    return InsiderContext(
        recent_count=recent_count,
        context_count=context_count,
        total_value=total,
        top_buyers=top_buyers[:3],
        summary=summary,
    )


def build_event_timeline(
    news: list[Any],
    sec_events: list[tuple[Any, EventClassification]],
    ticker: str,
    name: str,
    limit: int = 8,
) -> list[EventTimelineItem]:
    items: list[EventTimelineItem] = []

    for item in news:
        headline = str(getattr(item, "headline", "") or "").strip()
        summary = str(getattr(item, "summary", "") or "").strip()
        if not headline or not is_relevant(headline, summary, ticker, name):
            continue
        ev = classify_event(headline, summary, getattr(item, "source", None))
        text = _source_text(headline, summary)
        if ev.strength == 0 and not _looks_like_biotech_event(text):
            continue
        items.append(EventTimelineItem(
            event_date=_date_string(getattr(item, "published_at", None)),
            title=headline,
            event_type=ev.type if ev.strength > 0 else "Biotech-Ereignis",
            source=str(getattr(item, "source", None) or "News"),
            evidence=text,
            evidence_quote=headline,
        ))

    for filing, ev in sec_events:
        filing_date = str(getattr(filing, "filing_date", "") or "")
        filing_type = ev.type if ev.strength > 0 else str(getattr(filing, "event_type", "") or "8-K")
        press_release = str(getattr(filing, "press_release", "") or "")
        title = f"8-K: {getattr(filing, 'event_type', filing_type)}"
        items.append(EventTimelineItem(
            event_date=filing_date,
            title=title,
            event_type=filing_type,
            source="SEC 8-K",
            evidence=(press_release or f"{filing_date}: {title}").strip(),
            evidence_quote=_short_quote(press_release) or title,
        ))

    items.sort(key=lambda item: item.event_date or "9999-12-31")
    return items[:limit]


def detect_risk_signals(news: list[Any], limit: int = 5) -> list[RiskSignal]:
    signals: list[RiskSignal] = []
    seen: set[str] = set()
    for item in news:
        headline = str(getattr(item, "headline", "") or "").strip()
        summary = str(getattr(item, "summary", "") or "").strip()
        evidence = _source_text(headline, summary)
        low = evidence.lower()
        for label, detail, keywords in _RISK_RULES:
            if label in seen or not any(keyword in low for keyword in keywords):
                continue
            signals.append(RiskSignal(label=label, detail=detail, evidence=evidence, evidence_quote=headline or _short_quote(evidence)))
            seen.add(label)
            break
        if len(signals) >= limit:
            break
    return signals


def detect_upcoming_catalysts(news: list[Any], limit: int = 5) -> list[UpcomingCatalyst]:
    catalysts: list[UpcomingCatalyst] = []
    seen: set[tuple[str, str]] = set()
    for item in news:
        headline = str(getattr(item, "headline", "") or "").strip()
        summary = str(getattr(item, "summary", "") or "").strip()
        evidence = _source_text(headline, summary)
        low = evidence.lower()
        if not any(word in low for word in _CATALYST_FORWARD_WORDS):
            continue
        for catalyst_type, keywords in _CATALYST_RULES:
            if not any(keyword in low for keyword in keywords):
                continue
            key = (catalyst_type, headline)
            if key in seen:
                continue
            seen.add(key)
            catalysts.append(UpcomingCatalyst(
                catalyst_type=catalyst_type,
                date_text=_date_hint(evidence),
                detail=f"Quelle nennt bevorstehenden Katalysator: {headline}",
                evidence=evidence,
                evidence_quote=headline or _short_quote(evidence),
            ))
            break
        if len(catalysts) >= limit:
            break
    return catalysts


def build_research_brief(
    revenue_growth: float | None,
    insider_context: InsiderContext,
    event_timeline: list[EventTimelineItem],
    risk_signals: list[RiskSignal],
    upcoming_catalysts: list[UpcomingCatalyst],
    max_points: int = 5,
) -> ResearchBrief:
    bull: list[ResearchPoint] = []
    bear: list[ResearchPoint] = []

    primary_event = _strongest_timeline_event(event_timeline)
    if primary_event is not None:
        bull.append(ResearchPoint(
            text=f"Konkreter Turnaround-Katalysator: {primary_event.event_type}.",
            evidence=primary_event.evidence,
            evidence_quote=primary_event.evidence_quote,
        ))

    if revenue_growth is not None and revenue_growth > 0:
        evidence = f"Fundamentaldaten: Umsatzwachstum {revenue_growth * 100:.1f}%."
        bull.append(ResearchPoint(
            text=f"Umsatzwachstum stützt die Story: +{revenue_growth * 100:.1f}%.",
            evidence=evidence,
            evidence_quote=evidence,
        ))

    if insider_context.total_value > 0:
        bull.append(ResearchPoint(
            text=f"Insider-Kontext liefert Zusatzsignal: {insider_context.summary}",
            evidence=insider_context.summary,
            evidence_quote=insider_context.summary,
        ))

    if upcoming_catalysts:
        catalyst = upcoming_catalysts[0]
        bull.append(ResearchPoint(
            text=f"Bevorstehender Katalysator sichtbar: {catalyst.catalyst_type}.",
            evidence=catalyst.evidence,
            evidence_quote=catalyst.evidence_quote,
        ))

    if insider_context.recent_count == 0:
        bear.append(ResearchPoint(
            text="Keine qualifizierten Insider-Käufe in den letzten 7 Tagen.",
            evidence=insider_context.summary,
            evidence_quote=insider_context.summary,
        ))

    for risk in risk_signals:
        bear.append(ResearchPoint(
            text=f"{risk.label}: {risk.detail}",
            evidence=risk.evidence,
            evidence_quote=risk.evidence_quote,
        ))
        if len(bear) >= max_points:
            break

    if not bear:
        fallback = "Aus den verfügbaren 7-Tage-News und 8-K-Daten wurde kein zusätzliches Risikosignal extrahiert."
        bear.append(ResearchPoint(text="Keine zusätzlichen belegten Gegenargumente im ausgewerteten Material.", evidence=fallback, evidence_quote=fallback))

    return ResearchBrief(
        bull_case=bull[:max_points],
        bear_case=bear[:max_points],
        insider_context=insider_context,
        upcoming_catalysts=upcoming_catalysts,
        event_timeline=event_timeline,
        risk_signals=risk_signals,
    )


def _strongest_timeline_event(items: list[EventTimelineItem]) -> EventTimelineItem | None:
    preferred = [item for item in items if item.event_type not in ("Analystenmeinung", "Marktkommentar", "Biotech-Ereignis")]
    return preferred[-1] if preferred else (items[-1] if items else None)


def _buy_value(buy: Any) -> float | None:
    value = getattr(buy, "value", None)
    if value is None:
        return None
    return float(value)


def _source_text(headline: str, summary: str) -> str:
    return f"{headline}. {summary}".strip() if summary else headline


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _date_string(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "")
    return text[:10] if text else ""


def _short_quote(text: str, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:max_chars].rstrip()


def _looks_like_biotech_event(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in (
        "phase 1", "phase 2", "phase 3", "trial", "readout", "fda", "pdufa",
        "asco", "esmo", "milestone", "collaboration", "partnership", "approval",
        "dosed", "first participant",
    ))


def _date_hint(text: str) -> str:
    patterns = (
        r"\bQ[1-4]\s+20\d{2}\b",
        r"\bH[12]\s+20\d{2}\b",
        r"\b(?:ASCO|ESMO)\s+20\d{2}\b",
        r"\b20\d{2}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(0)
    return "Zeitpunkt laut Quelle nicht konkretisiert"
