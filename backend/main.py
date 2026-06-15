import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
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
    yield


app = FastAPI(
    title="PortfAIo API",
    description="Portfolio Tracker mit lokalem Ollama-Agenten",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolio.router, prefix="/api")
app.include_router(quotes.router, prefix="/api")
app.include_router(market_data.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(eval_router.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "portfaio-backend"}
