# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Coding Guidelines

### 1. Think Before Coding
- **State assumptions explicitly:** Before implementing, list your interpretation of the task. If uncertain, ask for clarification rather than guessing.
- **Surface tradeoffs:** If multiple paths exist, present them briefly before choosing one.
- **Push back:** If a request is likely to lead to bad architecture or unnecessary complexity, suggest a simpler alternative.
- **Stop on confusion:** If you find yourself "guessing" through a problem, stop and name exactly what is unclear.

### 2. Simplicity First
- **Minimalism:** Write the minimum amount of code required to solve the problem.
- **No speculative features:** Do not add "flexibility," "configurability," or abstractions for future use cases that weren't requested.
- **Prefer 100 lines over 1000:** If a solution can be implemented directly in 100 lines, do not build a 1000-line framework around it.
- **Avoid abstractions:** Do not create interfaces or wrappers for single-use code.

### 3. Surgical Changes
- **Stay in scope:** Touch only the files and lines strictly necessary for the task.
- **No orthogonal edits:** Do not "clean up" unrelated code, change comments, or reformat files unless explicitly asked.
- **Clean your own mess:** Only refactor code that you are actively modifying to fulfill the goal.

### 4. Goal-Driven Execution
- **Verifiable goals:** Transform vague tasks into testable outcomes (e.g., "Fix bug" → "Create reproduction test, then make it pass").
- **Test-first mindset:** Whenever possible, write or run a test to verify a change before declaring it finished.
- **Loop until verified:** Do not assume a fix works because the code "looks right." Use the terminal to confirm.

## Full Documentation

Human- and agent-facing docs live in [`docs/`](docs/README.md) (German). Start there for the *why*:
vision ([01](docs/01-vision-und-ziele.md)), architecture + trade-offs ([02](docs/02-architektur.md)),
**the hybrid agent** ([03](docs/03-agent-design.md)), backend ([04](docs/04-backend.md)),
frontend ([05](docs/05-frontend.md)), setup ([06](docs/06-setup-und-betrieb.md)),
decision log/ADRs ([07](docs/07-entscheidungslog.md)), API reference ([08](docs/08-api-referenz.md)),
**release v2.0-baseline changelog** ([09](docs/09-release-v2.0-baseline.md)).

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
docker exec portfaio-ollama ollama pull qwen3:14b
# or via the UI: KI-Analyse → "Modell laden"
```
Default model is `qwen3:14b` (see `backend/config.py`; needs ~9 GB on 16 GB Apple Silicon).
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
| `backend/routers/agent.py` | **SSE streaming agent** `/api/agent/analyze/{ticker}` (+ chat, rebalance, news) |
| `backend/routers/eval.py` | Eval metrics + ensemble backtest |
| `backend/agent/orchestrator.py` | Hybrid agent: pipeline → evidence-gated LLM explanation |
| `backend/agent/evidence.py` | Evidence catalog + `{{ev:id}}` render (anti-hallucination) |
| `backend/eval/faithfulness.py` | Sentence-level faithfulness gate |
| `backend/eval/backtest.py` | Walk-forward backtest of ensemble signals |
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
| `frontend/src/views/AnalysisView.vue` | **Main feature**: KI-Analyse with SSE streaming |
| `frontend/src/views/ChatView.vue` | KI-Chat (free-text, tool agent) |
| `frontend/src/views/EvalView.vue` | Agent metrics + ensemble backtest |
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
**analysis_metrics** — per-run signal, score, faithfulness, latency (eval)

## Git branches (v2.0-baseline)

- `main` — stable baseline (tag `v2.0-baseline`)
- `develop` — integration
- `feature/strategy-alt-a` — deterministic / Bollinger biotech screen
- `feature/strategy-alt-b` — news narrative / turnaround / insider

## Agent Architecture

Hybrid agent (see [docs/03-agent-design.md](docs/03-agent-design.md), [docs/09-release-v2.0-baseline.md](docs/09-release-v2.0-baseline.md)):
1. Frontend opens **GET** `/api/agent/analyze/{ticker}?current_prices=…` → SSE stream
2. Phase 1+2: deterministic pipeline → BUY/HOLD/SELL + score (no LLM)
3. Phase 3 (optional, `agentic=true`): tool loop with visible tool calls
4. Phase 4: LLM explains using `{{ev:id}}` placeholders → evidence render → faithfulness gate → SSE chunks
5. NO_DATA abort if no price history (no fabricated recommendation)

## Environment Variables (backend/.env)

```
DATABASE_URL=postgresql+asyncpg://portfaio:portfaio@localhost:5432/portfaio
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b
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
