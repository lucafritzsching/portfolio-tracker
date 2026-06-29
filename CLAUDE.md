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
**release v2.0-baseline changelog** ([09](docs/09-release-v2.0-baseline.md)),
**technical whole-project overview / flowcharts** ([14](docs/14-technische-codeuebersicht.md)).

## Architecture (Production)

Full-stack local webapp. The old `index.html` prototype is kept as reference only.

```
frontend/    Vue 3 + TypeScript + Vite   → localhost:5173
backend/     Python FastAPI              → localhost:8000
             PostgreSQL (Docker)         → localhost:5432
             Ollama (native host)        → localhost:11434
```

## Starting the App

> **Ollama runs natively on the host, not in Docker.** On macOS a container is CPU-only
> (no Metal/GPU passthrough) and far too slow/heavy for a 14B model, so `docker-compose`
> starts **only PostgreSQL** (plus an optional backend container). A native backend reaches
> Ollama at `localhost:11434`; the backend *container* reaches it via `host.docker.internal:11434`.

### 1. Start PostgreSQL (Docker)
```bash
docker-compose up -d postgres
```

### 2. Start Ollama + pull the model (native, first time only)
```bash
# install once from https://ollama.com/download  (or: brew install ollama)
ollama serve            # skip if Ollama already runs as a background app/service
ollama pull qwen3:14b   # or via the UI: KI-Analyse → "Modell laden"
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
| `backend/routers/agent.py` | **SSE agent endpoints** — primary `/api/agent/ask` (unified router) + status/pull-model (analyze/chat/rebalance/news kept, not in UI) |
| `backend/routers/eval.py` | Eval metrics + ensemble backtest |
| `backend/agent/orchestrator.py` | **`ask_stream` router** (Ollama tool-calling, visible 🔧-trace) + Alt-A pipeline (evidence-gated explanation) |
| `backend/agent/tools.py` | Tools + ToolExecutor: `screen_by_strategy`, `judge_news`, `run_statistical_model`, technicals, fundamentals, news (+ logging) |
| `backend/services/finder.py` | Strategy screen: mandate → LLM parse → yfinance `EquityQuery`/`screen` (+ fallback universe) |
| `backend/services/nl_target.py` | **Sector-agnostic** NL judge: relevance + subject-focus + **evidence-grounding** (no biotech rubric/clamp) |
| `backend/agent/data_science.py` | Technical indicators, ARIMA (interval confidence), RandomForest (current-bar + OOS accuracy) |
| `backend/agent/evidence.py` | Evidence catalog + `{{ev:id}}` render (Alt-A anti-hallucination) |
| `backend/eval/faithfulness.py` | Sentence-level faithfulness gate (Alt-A) |
| `backend/eval/backtest.py` | Walk-forward backtest of ensemble signals |
| `backend/agent/prompts.py` | German prompt templates (incl. `ROUTER_SYSTEM_PROMPT`) |

## Frontend Structure

| File | Purpose |
|------|---------|
| `frontend/src/types/index.ts` | TypeScript interfaces: Position, Transaction, SavingsPlan, etc. |
| `frontend/src/api/client.ts` | Typed fetch wrappers for all backend endpoints + EventSource for SSE |
| `frontend/src/stores/portfolio.ts` | Pinia store: positions, transactions, savings plans, stats |
| `frontend/src/stores/ui.ts` | Pinia store: active view, modals |
| `frontend/src/views/ChatView.vue` | **The single agent window** ("KI-Agent"): free-text → routes to screen/NL/statistics tools (SSE, visible tool-trace) + setup controls |
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

**Refactored to ONE routing chat agent** (see ADR-16/17 in [docs/07](docs/07-entscheidungslog.md),
[docs/12-data-science-methodik.md](docs/12-data-science-methodik.md), Flowchart 8 in
[docs/refactor_flowcharts.md](docs/refactor_flowcharts.md)):
1. Frontend (ChatView) opens **GET** `/api/agent/ask?question=…` → SSE stream
2. `orchestrator.ask_stream` runs an Ollama tool-loop (`_run_agent_loop`, temp 0, visible 🔧 tool-trace)
3. The LLM routes to the right tool:
   - `screen_by_strategy(mandate)` — deterministic yfinance screen (`services/finder.py`)
   - `judge_news(ticker, criterion)` — sector-agnostic NL judge, relevance + **evidence-grounding** (`services/nl_target.py`)
   - `run_statistical_model` / `calculate_technical_indicators` — ARIMA + RandomForest + technicals (`agent/data_science.py`)
4. Final turn synthesizes a grounded German explanation; tool calls + tracebacks are logged (`"agent"` logger)
5. Anti-hallucination: NL = must cite **real** headlines; statistics = deterministic + honest (interval confidence, OOS accuracy)

The deterministic **Alt-A hybrid pipeline** (`compute_ensemble` → BUY/HOLD/SELL, evidence-gated explanation,
faithfulness gate; `analyze_stock_stream`) still exists in the codebase but is no longer wired to the UI.

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
