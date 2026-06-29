"""Persistence for agent runs (chat history + trace) and standalone statistics.

One place that owns the SQL for the new AgentRun table and the quick-stats reuse of
AnalysisResult — so routers and the orchestrator stay free of query code.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AgentRun, AnalysisResult

logger = logging.getLogger("agent")


async def create_run(
    db: AsyncSession,
    *,
    question: str,
    answer: str,
    model: str,
    trace: list[dict],
    status: str = "ok",
    total_ms: int | None = None,
    eval_tokens: int | None = None,
    tokens_per_sec: float | None = None,
) -> AgentRun:
    """Persist one /ask invocation (question + final answer + full untruncated trace + perf)."""
    run = AgentRun(
        question=question,
        answer=answer,
        model=model,
        trace=trace,
        status=status,
        total_ms=total_ms,
        eval_tokens=eval_tokens,
        tokens_per_sec=tokens_per_sec,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def list_recent_runs(db: AsyncSession, limit: int = 50) -> list[AgentRun]:
    """Most recent agent runs first — this IS the server-side chat history."""
    return (
        await db.execute(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit))
    ).scalars().all()


async def get_run(db: AsyncSession, run_id: int) -> AgentRun | None:
    return (
        await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    ).scalar_one_or_none()


async def save_quick_stats(db: AsyncSession, ticker: str, arima, ml) -> AnalysisResult:
    """Persist a standalone /quick-stats result by REUSING AnalysisResult (it is ticker-specific).

    ``arima`` / ``ml`` are ModelForecast dataclasses. The structured summary is stored as JSON in
    ``analysis_text``; ``model="arima+rf"`` discriminates these rows from LLM analyses.
    """
    summary = {
        "arima": {"signal": arima.signal, "confidence": arima.confidence,
                  "forecast_30d": arima.forecast_30d, "details": arima.details},
        "random_forest": {"signal": ml.signal, "confidence": ml.confidence, "details": ml.details},
    }
    row = AnalysisResult(
        ticker=ticker,
        analysis_text=json.dumps(summary, ensure_ascii=False),
        model="arima+rf",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
