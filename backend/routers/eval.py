"""Evaluation endpoints: agent metrics and ensemble backtest."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from eval.backtest import run_backtest
from models import AnalysisMetric

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/metrics")
async def get_metrics(db: AsyncSession = Depends(get_db)):
    """Aggregate and recent analysis run metrics."""
    rows = (
        await db.execute(
            select(AnalysisMetric).order_by(AnalysisMetric.created_at.desc()).limit(50)
        )
    ).scalars().all()

    faithful_count = sum(1 for r in rows if r.faithful is True)
    faithful_total = sum(1 for r in rows if r.faithful is not None)
    avg_tps = (
        await db.execute(
            select(func.avg(AnalysisMetric.tokens_per_sec)).where(
                AnalysisMetric.tokens_per_sec.isnot(None)
            )
        )
    ).scalar()
    avg_ms = (
        await db.execute(
            select(func.avg(AnalysisMetric.total_ms)).where(
                AnalysisMetric.total_ms.isnot(None)
            )
        )
    ).scalar()

    def _row(r: AnalysisMetric) -> dict:
        return {
            "id": r.id,
            "ticker": r.ticker,
            "model": r.model,
            "signal": r.signal,
            "score": float(r.score),
            "confidence": float(r.confidence),
            "total_ms": r.total_ms,
            "tokens_per_sec": float(r.tokens_per_sec) if r.tokens_per_sec else None,
            "eval_tokens": r.eval_tokens,
            "faithful": r.faithful,
            "faithfulness_notes": r.faithfulness_notes,
            "created_at": r.created_at.isoformat(),
        }

    return {
        "aggregate": {
            "runs": len(rows),
            "avg_tokens_per_sec": round(float(avg_tps), 2) if avg_tps else None,
            "avg_total_ms": round(float(avg_ms)) if avg_ms else None,
            "faithful_rate": round(faithful_count / faithful_total, 2) if faithful_total else None,
        },
        "recent": [_row(r) for r in rows],
    }


@router.get("/backtest")
async def backtest(
    db: AsyncSession = Depends(get_db),
    tickers: str = Query("", description="Comma-separated tickers; empty = all portfolio positions"),
    horizon: int = Query(20, ge=5, le=60),
    step: int = Query(5, ge=1, le=20),
):
    """Walk-forward backtest of the deterministic ensemble."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] or None
    return await run_backtest(db, ticker_list, horizon_days=horizon, step_days=step)
