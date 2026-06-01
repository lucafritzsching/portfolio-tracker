# 4. Backend (FastAPI)

## Struktur

```
backend/
├── main.py            FastAPI-App, CORS, Router-Registrierung, DB-Init beim Start
├── config.py          Settings via pydantic-settings (liest .env)
├── database.py        Async-SQLAlchemy-Engine, Session-Factory, init_db()
├── models.py          ORM-Modelle = PostgreSQL-Schema
├── schemas.py         Pydantic-Schemas (Request/Response)
├── routers/
│   ├── portfolio.py   CRUD: Positionen, Transaktionen, Sparpläne, Import
│   ├── quotes.py      Finnhub-Kurs-Proxy (Einzel + Batch)
│   ├── market_data.py Historie, Fundamentaldaten, News, Warmup (dünne Wrapper um services/)
│   └── agent.py       SSE-Streaming-Endpunkte + Status + Modell-Pull
├── services/
│   └── market_data.py GEMEINSAME Fetch+Cache-Logik (yfinance/Finnhub) — einzige Datenquelle
├── agent/
│   ├── pipeline.py    Phase 1+2: Daten sammeln + build_ensemble_decision
│   ├── data_science.py Indikatoren, ARIMA, RandomForest, compute_ensemble
│   ├── orchestrator.py 4-Phasen-Stream, render_decision_block, echtes Streaming
│   ├── tools.py       Tool-Definitionen + ToolExecutor (Phase 3)
│   ├── sentiment.py   LLM-Aggregat-Sentiment (Keyword-Fallback in services/)
│   └── prompts.py     Deutsche Prompt-Templates
├── requirements.txt
└── Dockerfile
```

## Konfiguration (`config.py`)

`Settings` (pydantic-settings) liest `backend/.env`:

| Variable | Default | Zweck |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://portfaio:portfaio@localhost:5432/portfaio` | DB-Verbindung (async) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama-API |
| `OLLAMA_MODEL` | `qwen2.5:14b` | aktives Modell (7B = Fallback) |
| `FINNHUB_API_KEY` | – | Finnhub (Quotes + News) |
| `NEWS_API_KEY` | – | optional, derzeit ungenutzt |

> Im Docker-Container überschreibt `docker-compose.yml` `DATABASE_URL`/`OLLAMA_BASE_URL` mit den
> Service-Namen (`postgres`, `ollama`); die Secrets kommen aus `backend/.env` (`env_file`).
> Umgebungsvariablen haben Vorrang vor der `.env`-Datei.

## Datenbank (`database.py`, `models.py`)

Async SQLAlchemy 2.0 (`create_async_engine`, `async_sessionmaker`). Beim App-Start legt `init_db()`
alle Tabellen via `Base.metadata.create_all` an (kein Alembic – bewusst einfach gehalten; ein
Schema-Wechsel erfordert ein Neuanlegen der DB bzw. des Docker-Volumes).

### Tabellen (Schema)
| Tabelle | Wichtige Felder | Zweck |
|---|---|---|
| `positions` | ticker (unique), name, shares, sector, note, manual_buy_price, alerts_news | Portfolio-Positionen |
| `transactions` | ticker (FK→positions), type (buy/sell), shares, price, date, realized_pnl | Handelshistorie |
| `savings_plans` | ticker, monthly_amount, execution_day | Sparpläne |
| `savings_plan_executions` | plan_id (FK), date, amount, shares, price | Ausführungshistorie |
| `price_history` | ticker+date (unique idx), OHLCV | Kurs-Cache |
| `fundamentals_cache` | ticker (unique), pe_ratio, market_cap, eps, revenue_growth, …, fetched_at | Fundamentaldaten-Cache |
| `news_cache` | ticker, headline, summary, url, published_at, sentiment | News-Cache |
| `analysis_results` | ticker, analysis_text, model, created_at | gespeicherte Agent-Analysen |

**Beziehung & Kaskade:** `Position` ⇄ `Transaction` ist `cascade="all, delete-orphan"` mit FK
`ondelete="CASCADE"`. Wichtig: Beim **vollständigen Verkauf** wird die Position **nicht gelöscht**,
sondern `shares = 0` gesetzt – sonst würde die Kaskade die gesamte Transaktionshistorie (inkl.
realisiertem P&L) mitlöschen (siehe ADR-05 in [07-entscheidungslog.md](07-entscheidungslog.md)).

## Services: die einzige Datenquelle (`services/market_data.py`)

Zentralisiert allen externen Datenabruf + Caching. **Router und Agent rufen ausschließlich diese
Funktionen** – kein direkter yfinance-Aufruf in Routern/Tools (außer dem reichhaltigeren
`get_fundamentals`-Tool, das bewusst mehr Felder live holt).

| Funktion | Verhalten |
|---|---|
| `fetch_and_store_prices(ticker, db, period, force)` | yfinance-Tageskurse → `price_history`. Frische = neuester Balken ≤ `PRICE_FRESH_DAYS` (3 Tage); `force=True` erzwingt Refresh. Bei Fehler: Fallback auf Cache. |
| `fetch_and_store_fundamentals(ticker, db, force)` | yfinance `.info` → `fundamentals_cache`, TTL 12 h. |
| `fetch_and_store_news(ticker, db, days, force)` | Finnhub company-news → `news_cache`, TTL 1 h, **Dedup nach URL**. |
| `prices_to_dicts(rows)` | ORM-Zeilen → Dicts für die DS-Schicht. |
| `keyword_sentiment(text)` | Naiver Keyword-Score (Offline-Fallback). |

**Nicht-blockierend:** Jeder yfinance-Aufruf läuft via `asyncio.to_thread`, damit der Event-Loop
während des (mehrere Sekunden langen) Netzabrufs nicht blockiert.

## Router-Überblick

Alle Router sind unter dem Präfix `/api` registriert (`main.py`). Endpunktdetails:
[08-api-referenz.md](08-api-referenz.md).

- **`portfolio.py`** – CRUD für Positionen/Transaktionen/Sparpläne. Beim Buchen einer Transaktion
  werden `shares` aktualisiert; `execute` eines Sparplans legt bei Bedarf die Position automatisch an
  (sonst FK-Verletzung) und prüft `current_price > 0`.
- **`quotes.py`** – Finnhub-Quote-Proxy, validiert das Tickerformat; Batch-Variante für das Dashboard.
- **`market_data.py`** – dünne Wrapper um die Services + `POST /warmup` (cacht alle Portfolio-Ticker vor).
- **`agent.py`** – `GET /analyze/{ticker}` & `GET /analyze-portfolio` als SSE; `GET /status`
  (Ollama erreichbar? Modell vorhanden?); `POST /pull-model` (zieht das Modell, streamt Fortschritt).

### SSE & DB-Session (wichtiges Detail)
Die Agent-Endpunkte sind **GET** (EventSource kann nur GET) und öffnen die DB-Session **innerhalb des
Generators** (`async with AsyncSessionLocal() as db`), nicht über `Depends(get_db)`. Grund: Eine per
`Depends` injizierte Session würde beim Rückkehren der Handler-Funktion geschlossen – also *bevor*
`StreamingResponse` den Body sendet. Siehe ADR-04/ADR-08.

## Tests / lokale Prüfung ohne volle Infrastruktur

- `python -m py_compile **/*.py` – Syntaxprüfung.
- `compute_ensemble` ist als reine Funktion isoliert testbar (numpy/pandas/sklearn genügen;
  statsmodels optional – ARIMA degradiert sonst sauber zu HOLD).
