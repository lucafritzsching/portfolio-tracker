from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


# ── Transaction ──────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    type: Literal["buy", "sell"]
    shares: Decimal
    price: Decimal
    date: date
    realized_pnl: Decimal | None = None


class TransactionOut(TransactionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticker: str


# ── Position ──────────────────────────────────────────────────────────────────

class PositionCreate(BaseModel):
    ticker: str
    name: str
    shares: Decimal = Decimal("0")
    sector: str = "Sonstiges"
    note: str | None = None
    manual_buy_price: Decimal | None = None
    alerts_news: bool = True


class PositionUpdate(BaseModel):
    name: str | None = None
    sector: str | None = None
    note: str | None = None
    manual_buy_price: Decimal | None = None
    alerts_news: bool | None = None


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticker: str
    name: str
    shares: Decimal
    sector: str
    note: str | None
    manual_buy_price: Decimal | None
    alerts_news: bool
    created_at: datetime
    transactions: list[TransactionOut] = []


# ── Savings Plans ─────────────────────────────────────────────────────────────

class SavingsPlanCreate(BaseModel):
    ticker: str
    monthly_amount: Decimal
    execution_day: int


class SavingsPlanExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plan_id: int
    date: date
    amount: Decimal
    shares: Decimal
    price: Decimal


class SavingsPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticker: str
    monthly_amount: Decimal
    execution_day: int
    history: list[SavingsPlanExecutionOut] = []


# ── Market Data ───────────────────────────────────────────────────────────────

class QuoteOut(BaseModel):
    ticker: str
    current_price: float
    day_change: float
    previous_close: float
    name: str | None = None
    sector: str | None = None


class PriceHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class FundamentalsOut(BaseModel):
    ticker: str
    pe_ratio: float | None
    market_cap: float | None
    eps: float | None
    revenue_growth: float | None
    fifty_two_week_high: float | None
    fifty_two_week_low: float | None
    dividend_yield: float | None
    beta: float | None
    fetched_at: datetime | None


class NewsItemOut(BaseModel):
    id: int
    ticker: str
    headline: str
    summary: str | None
    url: str | None
    source: str | None
    published_at: datetime
    sentiment: float | None


# ── Screener ─────────────────────────────────────────────────────────────────

class ScreenerScoreBreakdownOut(BaseModel):
    label: str
    points: int
    max_points: int
    passed: bool
    detail: str


class ScreenerAgentAnalysisOut(BaseModel):
    turnaround_story: bool
    positive_events: list[str]
    risks: list[str]
    signal_quality: list[str]
    why_interesting: str


class ScreenerResearchPointOut(BaseModel):
    text: str
    evidence: str
    evidence_quote: str = ""


class ScreenerInsiderBuyerSummaryOut(BaseModel):
    name: str
    total_value: float
    buy_count: int


class ScreenerInsiderContextOut(BaseModel):
    recent_count: int = 0
    context_count: int = 0
    total_value: float = 0
    top_buyers: list[ScreenerInsiderBuyerSummaryOut] = Field(default_factory=list)
    summary: str = "Keine qualifizierten Insider-Käufe in den letzten 7 oder 180 Tagen."


class ScreenerUpcomingCatalystOut(BaseModel):
    catalyst_type: str
    date_text: str
    detail: str
    evidence: str
    evidence_quote: str = ""


class ScreenerEventTimelineItemOut(BaseModel):
    event_date: str
    title: str
    event_type: str
    source: str
    evidence: str
    evidence_quote: str = ""


class ScreenerRiskSignalOut(BaseModel):
    label: str
    detail: str
    evidence: str
    evidence_quote: str = ""


class ScreenerResearchBriefOut(BaseModel):
    bull_case: list[ScreenerResearchPointOut] = Field(default_factory=list)
    bear_case: list[ScreenerResearchPointOut] = Field(default_factory=list)
    insider_context: ScreenerInsiderContextOut = Field(default_factory=ScreenerInsiderContextOut)
    upcoming_catalysts: list[ScreenerUpcomingCatalystOut] = Field(default_factory=list)
    event_timeline: list[ScreenerEventTimelineItemOut] = Field(default_factory=list)
    risk_signals: list[ScreenerRiskSignalOut] = Field(default_factory=list)


class ScreenerScoreOut(BaseModel):
    strategy: str
    score: int
    label: str
    reasons: list[str]
    evidence: list[str]
    performance_90d: float | None = None
    turnaround_news: list[str] = Field(default_factory=list)
    score_breakdown: list[ScreenerScoreBreakdownOut] = Field(default_factory=list)
    decision_log: list[str] = Field(default_factory=list)
    qualifies: bool = False
    agent_analysis: ScreenerAgentAnalysisOut | None = None
    biotech_events: list[str] = Field(default_factory=list)
    story_de: str = ""
    evidence_quote: str = ""
    used_llm: bool = False
    event_type: str = ""
    event_strength: int = 0
    event_evidence: str = ""


class ScreenerInsiderBuyOut(BaseModel):
    name: str
    transaction_date: date | None
    filing_date: date | None
    shares: float
    price: float | None
    value: float | None


class ScreenerFilingOut(BaseModel):
    filing_date: str
    event_type: str
    url: str


class ScreenerCandidateOut(BaseModel):
    ticker: str
    name: str
    exchange: str
    industry: str
    market_cap: float | None
    revenue_growth: float | None
    performance_90d: float | None
    alt_a: ScreenerScoreOut
    alt_b: ScreenerScoreOut
    turnaround_news: list[str]
    insider_buys: list[ScreenerInsiderBuyOut]
    insider_context_buys: list[ScreenerInsiderBuyOut] = Field(default_factory=list)
    biotech_events: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    sec_filings: list[ScreenerFilingOut] = Field(default_factory=list)
    research: ScreenerResearchBriefOut = Field(default_factory=ScreenerResearchBriefOut)


class ScreenerFunnelStepOut(BaseModel):
    label: str
    count: int
    detail: str


class ScreenerWindowsOut(BaseModel):
    event_days: int
    context_days: int
    insider_context_days: int


class ScreenerResponseOut(BaseModel):
    universe_count: int
    filter_funnel: list[ScreenerFunnelStepOut] = Field(default_factory=list)
    windows: ScreenerWindowsOut
    candidates: list[ScreenerCandidateOut]
    created_at: datetime | None = None
    universe_source: str = "kuratiert"
    universe_updated_at: datetime | None = None


class ScreenerUniverseStatusOut(BaseModel):
    count: int
    updated_at: datetime | None = None
    source: str = "kuratiert"


# ── Import from localStorage ──────────────────────────────────────────────────

class LegacyPosition(BaseModel):
    ticker: str
    name: str
    shares: float
    buyPrice: float | None = None
    currentPrice: float | None = None
    dayChange: float | None = None
    sector: str = "Sonstiges"
    note: str | None = None
    manualBuyPrice: float | None = None


class LegacyTransaction(BaseModel):
    ticker: str
    type: Literal["buy", "sell"]
    shares: float
    price: float
    date: str
    realizedPnl: float | None = None


class ImportPayload(BaseModel):
    positions: list[LegacyPosition]
    transactions: list[LegacyTransaction] = []


# ── Agent ─────────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    ticker: str
    include_portfolio_context: bool = True
