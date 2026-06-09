from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas import (
    ScreenerCandidateOut,
    ScreenerFunnelStepOut,
    ScreenerInsiderBuyOut,
    ScreenerResponseOut,
    ScreenerScoreOut,
    ScreenerWindowsOut,
)
from services.screener import screen_biotech_turnaround

router = APIRouter(prefix="/screener", tags=["screener"])


@router.get("/alt-b", response_model=ScreenerResponseOut)
async def get_alt_b_screener(
    limit: int = Query(12, ge=1, le=25),
    min_score: int = Query(0, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
):
    screen = await screen_biotech_turnaround(db, limit=limit, min_score=min_score)
    return ScreenerResponseOut(
        universe_count=screen.universe_count,
        filter_funnel=[ScreenerFunnelStepOut(**asdict(step)) for step in screen.filter_funnel],
        windows=ScreenerWindowsOut(**asdict(screen.windows)),
        candidates=[_candidate_out(candidate) for candidate in screen.candidates],
    )


def _score_out(score) -> ScreenerScoreOut:
    return ScreenerScoreOut(**asdict(score))


def _candidate_out(candidate) -> ScreenerCandidateOut:
    return ScreenerCandidateOut(
        ticker=candidate.ticker,
        name=candidate.name,
        exchange=candidate.exchange,
        industry=candidate.industry,
        market_cap=candidate.market_cap,
        revenue_growth=candidate.revenue_growth,
        performance_90d=candidate.performance_90d,
        alt_a=_score_out(candidate.alt_a),
        alt_b=_score_out(candidate.alt_b),
        turnaround_news=candidate.turnaround_news,
        insider_buys=[
            ScreenerInsiderBuyOut(
                name=buy.name,
                transaction_date=buy.transaction_date,
                filing_date=buy.filing_date,
                shares=buy.shares,
                price=buy.price,
                value=buy.value,
            )
            for buy in candidate.insider_buys
        ],
        insider_context_buys=[
            ScreenerInsiderBuyOut(
                name=buy.name,
                transaction_date=buy.transaction_date,
                filing_date=buy.filing_date,
                shares=buy.shares,
                price=buy.price,
                value=buy.value,
            )
            for buy in candidate.insider_context_buys
        ],
        biotech_events=candidate.biotech_events,
        risk_flags=candidate.risk_flags,
    )
