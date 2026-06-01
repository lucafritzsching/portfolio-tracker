from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Position, Transaction, SavingsPlan, SavingsPlanExecution
from schemas import (
    PositionCreate, PositionUpdate, PositionOut,
    TransactionCreate, TransactionOut,
    SavingsPlanCreate, SavingsPlanOut,
    ImportPayload,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ── Positions ─────────────────────────────────────────────────────────────────

@router.get("/positions", response_model=list[PositionOut])
async def list_positions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Position).order_by(Position.created_at))
    return result.scalars().all()


@router.post("/positions", response_model=PositionOut, status_code=201)
async def create_position(body: PositionCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Position).where(Position.ticker == body.ticker.upper()))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Position {body.ticker.upper()} existiert bereits")
    pos = Position(**body.model_dump(), ticker=body.ticker.upper())
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


@router.get("/positions/{ticker}", response_model=PositionOut)
async def get_position(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Position).where(Position.ticker == ticker.upper()))
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(404, f"Position {ticker.upper()} nicht gefunden")
    return pos


@router.patch("/positions/{ticker}", response_model=PositionOut)
async def update_position(ticker: str, body: PositionUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Position).where(Position.ticker == ticker.upper()))
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(404, f"Position {ticker.upper()} nicht gefunden")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(pos, field, value)
    await db.commit()
    await db.refresh(pos)
    return pos


@router.delete("/positions/{ticker}", status_code=204)
async def delete_position(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Position).where(Position.ticker == ticker.upper()))
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(404, f"Position {ticker.upper()} nicht gefunden")
    await db.delete(pos)
    await db.commit()


# ── Transactions ──────────────────────────────────────────────────────────────

@router.post("/positions/{ticker}/transactions", response_model=TransactionOut, status_code=201)
async def add_transaction(ticker: str, body: TransactionCreate, db: AsyncSession = Depends(get_db)):
    ticker = ticker.upper()
    result = await db.execute(select(Position).where(Position.ticker == ticker))
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(404, f"Position {ticker} nicht gefunden")

    tx = Transaction(ticker=ticker, **body.model_dump())
    db.add(tx)

    if body.type == "buy":
        pos.shares = pos.shares + body.shares
    else:
        pos.shares = pos.shares - body.shares
        if pos.shares <= Decimal("0.000001"):
            await db.delete(pos)
            await db.commit()
            return TransactionOut.model_validate({**body.model_dump(), "id": 0, "ticker": ticker})

    await db.commit()
    await db.refresh(tx)
    return tx


@router.get("/positions/{ticker}/transactions", response_model=list[TransactionOut])
async def list_transactions(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Transaction).where(Transaction.ticker == ticker.upper()).order_by(Transaction.date)
    )
    return result.scalars().all()


# ── Savings Plans ─────────────────────────────────────────────────────────────

@router.get("/savings-plans", response_model=list[SavingsPlanOut])
async def list_savings_plans(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SavingsPlan))
    return result.scalars().all()


@router.post("/savings-plans", response_model=SavingsPlanOut, status_code=201)
async def create_savings_plan(body: SavingsPlanCreate, db: AsyncSession = Depends(get_db)):
    plan = SavingsPlan(**body.model_dump(), ticker=body.ticker.upper())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/savings-plans/{plan_id}", status_code=204)
async def delete_savings_plan(plan_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SavingsPlan).where(SavingsPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Sparplan nicht gefunden")
    await db.delete(plan)
    await db.commit()


@router.post("/savings-plans/{plan_id}/execute", response_model=SavingsPlanOut)
async def execute_savings_plan(plan_id: int, current_price: float, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SavingsPlan).where(SavingsPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Sparplan nicht gefunden")

    price = Decimal(str(current_price))
    shares_bought = plan.monthly_amount / price

    execution = SavingsPlanExecution(
        plan_id=plan_id,
        date=datetime.utcnow().date(),
        amount=plan.monthly_amount,
        shares=shares_bought,
        price=price,
    )
    db.add(execution)

    pos_result = await db.execute(select(Position).where(Position.ticker == plan.ticker))
    pos = pos_result.scalar_one_or_none()
    if pos:
        pos.shares = pos.shares + shares_bought

    tx = Transaction(
        ticker=plan.ticker,
        type="buy",
        shares=shares_bought,
        price=price,
        date=datetime.utcnow().date(),
    )
    db.add(tx)

    await db.commit()
    await db.refresh(plan)
    return plan


# ── Import from localStorage ──────────────────────────────────────────────────

@router.post("/import", status_code=201)
async def import_legacy_data(payload: ImportPayload, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Position))
    if result.scalars().first():
        raise HTTPException(409, "Datenbank ist nicht leer. Import abgebrochen.")

    for lp in payload.positions:
        pos = Position(
            ticker=lp.ticker.upper(),
            name=lp.name,
            shares=Decimal(str(lp.shares)),
            sector=lp.sector,
            note=lp.note,
            manual_buy_price=Decimal(str(lp.manualBuyPrice)) if lp.manualBuyPrice else None,
        )
        db.add(pos)

    for lt in payload.transactions:
        tx = Transaction(
            ticker=lt.ticker.upper(),
            type=lt.type,
            shares=Decimal(str(lt.shares)),
            price=Decimal(str(lt.price)),
            date=datetime.fromisoformat(lt.date).date(),
            realized_pnl=Decimal(str(lt.realizedPnl)) if lt.realizedPnl is not None else None,
        )
        db.add(tx)

    await db.commit()
    return {"imported_positions": len(payload.positions), "imported_transactions": len(payload.transactions)}
