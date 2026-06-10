"""Shared data types, constants and tiny helpers for the screener strategies.

Kept dependency-free (stdlib only) so the pure scoring core (``alt_b_signal.py``) and
the I/O orchestration (``screener.py``) can both import from here without an import
cycle. Nothing in this module does I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# ── Shared screener domain constants ─────────────────────────────────────────────
MIN_INSIDER_VALUE = 50_000   # min $ value for a qualifying insider open-market buy
CONTEXT_DAYS = 90            # lookback window for performance / turnaround context


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
    trace: list = field(default_factory=list)  # list[trace.TraceStep] — structured decision trace


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
