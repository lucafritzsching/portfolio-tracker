from datetime import datetime, date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict


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
