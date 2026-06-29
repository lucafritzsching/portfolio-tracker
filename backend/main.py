import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from database import init_db, seed_demo_positions
from routers import portfolio, quotes, market_data, agent
from routers import eval as eval_router

# Durchgehendes Logging: Tool-Calls, Routing-Schritte und Tracebacks landen sichtbar im Server-Log
# (statt stumm im SSE-`[FEHLER]`-String zu verschwinden). Der "agent"-Logger wird überall genutzt.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("agent").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_demo_positions()   # only seeds when the portfolio is empty
    yield


app = FastAPI(
    title="PortfAIo API",
    description="Portfolio Tracker mit lokalem Ollama-Agenten",
    version="2.0.0",
    lifespan=lifespan,
)

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

app.include_router(portfolio.router, prefix="/api")
app.include_router(quotes.router, prefix="/api")
app.include_router(market_data.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(eval_router.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "portfaio-backend"}
