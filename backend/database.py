from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from config import settings

# Pool-Parameter nur für Server-DBs (Postgres). SQLite (Tests) nutzt ein eigenes Pool-Modell
# und akzeptiert pool_size/max_overflow nicht — daher konditional.
_engine_kwargs: dict = {"echo": False, "pool_pre_ping": settings.db_pool_pre_ping}
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# A small diversified demo portfolio so the app isn't empty on first start (demo convenience).
# (ticker, name, sector, shares, manual_buy_price)
_DEMO_POSITIONS = [
    ("AAPL", "Apple Inc.", "Technologie", 10, 180.0),
    ("MSFT", "Microsoft Corp.", "Technologie", 5, 380.0),
    ("NVDA", "NVIDIA Corp.", "Technologie", 6, 120.0),
    ("JPM", "JPMorgan Chase & Co.", "Finanzen", 8, 190.0),
    ("JNJ", "Johnson & Johnson", "Gesundheit", 6, 155.0),
    ("XOM", "Exxon Mobil Corp.", "Energie", 12, 110.0),
    ("PG", "Procter & Gamble Co.", "Konsumgüter", 7, 160.0),
    ("KO", "Coca-Cola Co.", "Konsumgüter", 15, 60.0),
    ("CAT", "Caterpillar Inc.", "Industrie", 4, 330.0),
    ("SPY", "SPDR S&P 500 ETF", "ETF / Fonds", 3, 500.0),
]


async def seed_demo_positions():
    """Insert the demo portfolio ONLY if the positions table is empty (idempotent — never touches
    an existing portfolio). Keeps the demo from starting on an empty screen."""
    from sqlalchemy import select, func
    from models import Position

    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(Position))).scalar() or 0
        if count > 0:
            return
        for ticker, name, sector, shares, price in _DEMO_POSITIONS:
            db.add(Position(ticker=ticker, name=name, sector=sector, shares=shares, manual_buy_price=price))
        await db.commit()
