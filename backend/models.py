from datetime import datetime, date
from decimal import Decimal
from typing import Any
from sqlalchemy import String, Numeric, Integer, Boolean, Date, DateTime, Text, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    shares: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    sector: Mapped[str] = mapped_column(String(100), nullable=False, default="Sonstiges")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_buy_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    alerts_news: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="position", cascade="all, delete-orphan", lazy="selectin"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), ForeignKey("positions.ticker", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(4), nullable=False)  # 'buy' | 'sell'
    shares: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    position: Mapped["Position"] = relationship(back_populates="transactions")


class SavingsPlan(Base):
    __tablename__ = "savings_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    execution_day: Mapped[int] = mapped_column(Integer, nullable=False)

    history: Mapped[list["SavingsPlanExecution"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )


class SavingsPlanExecution(Base):
    __tablename__ = "savings_plan_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("savings_plans.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    shares: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    plan: Mapped["SavingsPlan"] = relationship(back_populates="history")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_price_history_ticker_date", "ticker", "date", unique=True),
    )


class FundamentalsCache(Base):
    __tablename__ = "fundamentals_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    pe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    eps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    revenue_growth: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    fifty_two_week_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    fifty_two_week_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    dividend_yield: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    beta: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NewsCache(Base):
    __tablename__ = "news_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sentiment: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    __table_args__ = (
        Index("ix_news_cache_ticker_published", "ticker", "published_at"),
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    analysis_text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentRun(Base):
    """One row per live `/ask` agent invocation — the durable chat history AND full audit trail.

    The free-text routing agent has no fixed ticker and no single decision, so it does not fit the
    ticker/decision-centric AnalysisResult/AnalysisMetric tables. The whole tool trace (tool calls +
    their results — which already contain news judgements, rankings, scores, evidence) is stored
    UNTRUNCATED as one JSON column; no per-tool child tables (kept deliberately simple).
    """
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # List of {step, tool, args, result} — the complete, untruncated tool trace.
    trace: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # ok | error

    # Ollama timing (best-effort, may be absent)
    total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eval_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_per_sec: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AnalysisMetric(Base):
    """One row per agent analysis run — used to track & evaluate agent performance.

    Captures the deterministic decision, the LLM latency/throughput (from Ollama's
    own timing fields) and an automated faithfulness check of the explanation text.
    """
    __tablename__ = "analysis_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    # Deterministic decision snapshot
    signal: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY / HOLD / SELL
    score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    # LLM performance (from Ollama timing fields)
    total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    load_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eval_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_per_sec: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    # Explanation faithfulness check
    faithful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    faithfulness_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
