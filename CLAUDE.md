# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Full Documentation

Human- and agent-facing docs live in [`docs/`](docs/README.md) (German). Start there for the *why*:
vision ([01](docs/01-vision-und-ziele.md)), architecture + trade-offs ([02](docs/02-architektur.md)),
**the hybrid agent** ([03](docs/03-agent-design.md)), backend ([04](docs/04-backend.md)),
frontend ([05](docs/05-frontend.md)), setup ([06](docs/06-setup-und-betrieb.md)),
decision log/ADRs ([07](docs/07-entscheidungslog.md)), API reference ([08](docs/08-api-referenz.md)).

## Architecture (Production)

Full-stack local webapp. The old `index.html` prototype is kept as reference only.

```
frontend/    Vue 3 + TypeScript + Vite   → localhost:5173
backend/     Python FastAPI              → localhost:8000
             PostgreSQL (Docker)         → localhost:5432
             Ollama (Docker)             → localhost:11434
```

## Starting the App

### 1. Start backend services (PostgreSQL + Ollama)
```bash
docker-compose up -d
```

### 2. Pull the AI model (first time only)
```bash
docker exec portfaio-ollama ollama pull qwen2.5:14b
# or via the UI: KI-Analyse → "Modell laden"
```
Default model is `qwen2.5:14b` (needs ~9 GB, comfortable on 16 GB Apple Silicon).
Fallback for low-RAM machines: set `OLLAMA_MODEL=qwen2.5:7b` in `backend/.env`.

### 3. Start FastAPI backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # once
pip install -r requirements.txt                      # once
cp .env.example .env                                 # add FINNHUB_API_KEY
uvicorn main:app --reload
```

### 4. Start Vue frontend
```bash
cd frontend
npm install   # once
npm run dev
```

Open http://localhost:5173

## Backend Structure

| File | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app, CORS, router registration, DB init on startup |
| `backend/config.py` | Settings via pydantic-settings + .env |
| `backend/database.py` | SQLAlchemy async engine, `init_db()` |
| `backend/models.py` | ORM models: Position, Transaction, SavingsPlan, PriceHistory, FundamentalsCache, NewsCache, AnalysisResult |
| `backend/schemas.py` | Pydantic request/response schemas |
| `backend/routers/portfolio.py` | CRUD for positions, transactions, savings plans; `/import` for localStorage migration |
| `backend/routers/quotes.py` | Finnhub stock price proxy |
| `backend/routers/market_data.py` | Historical prices, fundamentals, news (yfinance + Finnhub) |
| `backend/routers/agent.py` | **SSE streaming agent endpoint** `/api/agent/analyze/{ticker}` |
| `backend/agent/orchestrator.py` | **Agent loop**: tool-calling → Ollama → tool-calling → final SSE stream |
| `backend/agent/tools.py` | Tool definitions (Qwen tool-calling format) + ToolExecutor |
| `backend/agent/data_science.py` | Technical indicators, ARIMA forecast, Random Forest signal |
| `backend/agent/prompts.py` | German prompt templates |

## Frontend Structure

| File | Purpose |
|------|---------|
| `frontend/src/types/index.ts` | TypeScript interfaces: Position, Transaction, SavingsPlan, etc. |
| `frontend/src/api/client.ts` | Typed fetch wrappers for all backend endpoints + EventSource for SSE |
| `frontend/src/stores/portfolio.ts` | Pinia store: positions, transactions, savings plans, stats |
| `frontend/src/stores/ui.ts` | Pinia store: active view, modals |
| `frontend/src/views/AnalysisView.vue` | **Main feature**: KI-Analyse with SSE EventSource streaming |
| `frontend/src/views/DashboardView.vue` | Metrics, charts, positions table |
| `frontend/src/views/PositionsView.vue` | Position cards, transaction history, transaction modal |
| `frontend/src/views/SavingsView.vue` | Savings plans management |
| `frontend/src/views/NewsView.vue` | News feed via Finnhub News API |
| `frontend/src/composables/useFormatters.ts` | fmt(), fmtPct(), fmtCurrency(), fmtDate() |
| `frontend/src/composables/useSignal.ts` | getSignal() → Verkaufen/Halten/Nachkaufen/Beobachten |

## Data Model (PostgreSQL)

**positions** — ticker (unique), name, shares, sector, note, manual_buy_price, alerts_news
**transactions** — ticker (FK), type (buy/sell), shares, price, date, realized_pnl
**savings_plans** — ticker, monthly_amount, execution_day
**savings_plan_executions** — plan_id (FK), date, amount, shares, price
**price_history** — ticker+date (unique index), OHLCV
**fundamentals_cache** — P/E, market_cap, EPS, revenue_growth, 52w high/low, beta, dividend_yield
**news_cache** — ticker, headline, summary, url, published_at, sentiment
**analysis_results** — ticker, analysis_text, model, created_at

## Agent Architecture

The Ollama agent uses **Qwen 2.5 tool-calling**:
1. Frontend sends POST to `/api/agent/analyze/{ticker}` → SSE stream
2. FastAPI builds context from PostgreSQL, calls Ollama with tool definitions
3. Agent calls tools: `get_historical_prices`, `calculate_technical_indicators`, `get_fundamentals`, `get_news`, `run_statistical_model`, `get_portfolio_context`
4. DS pipeline: RSI, MACD, Bollinger, ARIMA forecast, Random Forest Buy/Hold/Sell
5. Agent synthesizes → final recommendation streams token-by-token to frontend

## Environment Variables (backend/.env)

```
DATABASE_URL=postgresql+asyncpg://portfaio:portfaio@localhost:5432/portfaio
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b
FINNHUB_API_KEY=<your key from finnhub.io>
NEWS_API_KEY=<optional, newsapi.org>
```

## Signal Logic (unchanged from prototype)

`getSignal(pos)` in `frontend/src/composables/useSignal.ts`:
- Return > +20% → "Verkaufen"
- Return < -12% → "Nachkaufen"
- |dayChange| > 4% → "Beobachten"
- else → "Halten"

## Legacy Prototype

The original single-file prototype is at `index.html` (root). It still works standalone for reference.
To migrate localStorage data to the new backend: POST to `/api/portfolio/import` with the JSON dump.
