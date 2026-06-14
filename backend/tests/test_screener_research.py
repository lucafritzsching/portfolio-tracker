"""Tests for the Alt-B research layer added on top of the unchanged gate/score."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.event_strength import EventClassification
from services.screener import InsiderBuy, ScreenerCandidate, StrategyScore, candidate_out, score_alt_b
from services.sec_filings import Filing8K
from services.screener_research import (
    EventTimelineItem,
    InsiderContext,
    ResearchBrief,
    ResearchPoint,
    RiskSignal,
    UpcomingCatalyst,
    aggregate_insider_context,
    build_event_timeline,
    build_research_brief,
    detect_risk_signals,
    detect_upcoming_catalysts,
)


def _news(headline: str, summary: str = "", published_at: datetime | None = None, source: str = "GlobeNewswire"):
    return SimpleNamespace(
        headline=headline,
        summary=summary,
        source=source,
        published_at=published_at or datetime(2026, 6, 7),
    )


def _fund(revenue_growth: float | None = 0.15):
    return SimpleNamespace(market_cap=2_000_000_000, revenue_growth=revenue_growth)


def test_score_exposes_primary_event_without_changing_score():
    news = [_news("XYZ Announces Positive Phase 2 Data in Lupus")]

    score = score_alt_b(_fund(), [], news, [], ticker="XYZ", name="XYZ Bio")

    assert score.score == 60
    assert score.qualifies
    assert score.event_type == "Positive Phase-2 Daten"
    assert score.event_strength == 4
    assert score.event_evidence == "XYZ Announces Positive Phase 2 Data in Lupus"


def test_insider_context_summarizes_180_day_volume_when_7_day_window_is_empty():
    context = aggregate_insider_context(
        recent_buys=[],
        context_buys=[
            InsiderBuy("CEO", date(2026, 2, 1), date(2026, 2, 2), 1_000_000, 100.0),
            InsiderBuy("CFO", date(2026, 4, 1), date(2026, 4, 2), 200_000, 100.0),
            InsiderBuy("CEO", date(2026, 5, 1), date(2026, 5, 2), 50_000, 100.0),
        ],
        window_days=180,
    )

    assert context.recent_count == 0
    assert context.context_count == 3
    assert context.total_value == 125_000_000
    assert context.top_buyers[0].name == "CEO"
    assert context.top_buyers[0].total_value == 105_000_000
    assert "Keine Käufe in den letzten 7 Tagen" in context.summary
    assert "$125,000,000" in context.summary


def test_event_timeline_is_chronological_and_evidence_backed():
    filing = Filing8K("XYZ", "2026-06-07", ["8.01"], "acc", "doc.htm", "Sonstiges Wesentliches", True)
    timeline = build_event_timeline(
        news=[
            _news("XYZ Announces Phase 1 Trial Started", "First participant dosed.", datetime(2026, 6, 4)),
            _news("XYZ Receives Milestone Payment from Partner", "$20 million milestone payment.", datetime(2026, 6, 6)),
        ],
        sec_events=[(filing, EventClassification(4, "Meilensteinzahlung aus Kooperation", "positive", False, True))],
        ticker="XYZ",
        name="XYZ Bio",
    )

    assert [item.event_date for item in timeline] == ["2026-06-04", "2026-06-06", "2026-06-07"]
    assert timeline[0].evidence
    assert timeline[1].event_type == "Meilensteinzahlung aus Kooperation"
    assert timeline[2].source == "SEC 8-K"


def test_risk_signals_and_upcoming_catalysts_use_source_quotes():
    news = [
        _news("XYZ Files Shelf Offering", "The company may issue up to $200 million of common stock."),
        _news("XYZ Says Phase 3 Study Delayed", "FDA feedback delayed the trial start."),
        _news("XYZ to Present Phase 2 Readout at ASCO", "The company expects a Phase 2 readout at ASCO 2026."),
    ]

    risks = detect_risk_signals(news)
    catalysts = detect_upcoming_catalysts(news)

    assert [risk.label for risk in risks] == ["Shelf Offering", "FDA-/Studienverzögerung"]
    assert all(risk.evidence_quote and risk.evidence_quote in risk.evidence for risk in risks)
    assert catalysts[0].catalyst_type == "Phase-2 Readout"
    assert catalysts[0].evidence_quote in catalysts[0].evidence


def test_bull_bear_brief_only_contains_evidence_backed_points():
    insider_context = aggregate_insider_context(
        recent_buys=[],
        context_buys=[InsiderBuy("CEO", date(2026, 2, 1), date(2026, 2, 2), 1_000, 100.0)],
    )
    timeline = build_event_timeline(
        news=[_news("XYZ Receives Milestone Payment from Partner", "$20 million milestone payment.")],
        sec_events=[],
        ticker="XYZ",
        name="XYZ Bio",
    )
    risks = detect_risk_signals([
        _news("XYZ Prices Public Offering", "The public offering could dilute existing shareholders."),
    ])
    catalysts = detect_upcoming_catalysts([
        _news("XYZ to Present Phase 2 Readout at ASCO", "The company expects a Phase 2 readout at ASCO 2026."),
    ])

    brief = build_research_brief(
        revenue_growth=0.20,
        insider_context=insider_context,
        event_timeline=timeline,
        risk_signals=risks,
        upcoming_catalysts=catalysts,
    )

    assert 1 <= len(brief.bull_case) <= 5
    assert 1 <= len(brief.bear_case) <= 5
    assert all(point.evidence for point in brief.bull_case + brief.bear_case)
    assert any("Umsatzwachstum" in point.text for point in brief.bull_case)
    assert any("Keine qualifizierten Insider-Käufe in den letzten 7 Tagen" in point.text for point in brief.bear_case)
    assert any("Verwässerungsrisiko" in point.text for point in brief.bear_case)


def test_candidate_output_contract_includes_research_fields():
    research = ResearchBrief(
        bull_case=[ResearchPoint("Bull", "Source text", "Source")],
        bear_case=[ResearchPoint("Bear", "Risk text", "Risk")],
        insider_context=InsiderContext(
            recent_count=0,
            context_count=1,
            total_value=100_000,
            summary="Keine Käufe in den letzten 7 Tagen, aber Insider-Käufe über $100,000 in den letzten 180 Tagen.",
        ),
        upcoming_catalysts=[UpcomingCatalyst("Phase-2 Readout", "ASCO 2026", "Detail", "Evidence", "Evidence")],
        event_timeline=[EventTimelineItem("2026-06-07", "Title", "Positive Phase-2 Daten", "News", "Evidence", "Title")],
        risk_signals=[RiskSignal("Verwässerungsrisiko", "Detail", "Evidence", "Evidence")],
    )
    candidate = ScreenerCandidate(
        ticker="XYZ",
        name="XYZ Bio",
        exchange="NASDAQ",
        industry="Biotechnology",
        market_cap=2_000_000_000,
        revenue_growth=0.2,
        performance_90d=-0.1,
        alt_a=StrategyScore("ALT_A", 0, "n/a", [], []),
        alt_b=StrategyScore(
            "ALT_B",
            60,
            "Watchlist Turnaround",
            [],
            [],
            qualifies=True,
            event_type="Positive Phase-2 Daten",
            event_strength=4,
            event_evidence="XYZ Announces Positive Phase 2 Data",
        ),
        turnaround_news=["XYZ Announces Positive Phase 2 Data"],
        insider_buys=[],
        research=research,
    )

    out = candidate_out(candidate)

    assert out.alt_b.event_type == "Positive Phase-2 Daten"
    assert out.alt_b.event_strength == 4
    assert out.research.bull_case[0].evidence_quote == "Source"
    assert out.research.insider_context.total_value == 100_000
    assert out.research.upcoming_catalysts[0].catalyst_type == "Phase-2 Readout"
