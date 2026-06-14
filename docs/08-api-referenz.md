# 8. API-Referenz

Basis-URL: `http://localhost:8000`. Alle fachlichen Endpunkte liegen unter `/api`.
Interaktive Doku (Swagger UI): `http://localhost:8000/docs`.

Ticker werden serverseitig in Großbuchstaben normalisiert.

## Health

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/health` | Liveness-Check → `{ "status": "ok", "service": "portfaio-backend" }` |

## Portfolio (`/api/portfolio`)

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/positions` | Alle Positionen (inkl. Transaktionen) |
| POST | `/positions` | Position anlegen. Body: `{ ticker, name, shares?, sector?, note?, manual_buy_price?, alerts_news? }` |
| GET | `/positions/{ticker}` | Einzelne Position |
| PATCH | `/positions/{ticker}` | Felder aktualisieren: `{ name?, sector?, note?, manual_buy_price?, alerts_news? }` |
| DELETE | `/positions/{ticker}` | Position löschen |
| POST | `/positions/{ticker}/transactions` | Transaktion buchen. Body: `{ type: "buy"\|"sell", shares, price, date, realized_pnl? }`. Aktualisiert `shares`; bei Vollverkauf `shares=0` (Position bleibt). |
| GET | `/positions/{ticker}/transactions` | Transaktionshistorie |
| GET | `/savings-plans` | Alle Sparpläne (inkl. Ausführungshistorie) |
| POST | `/savings-plans` | Sparplan anlegen. Body: `{ ticker, monthly_amount, execution_day }` |
| DELETE | `/savings-plans/{plan_id}` | Sparplan löschen |
| POST | `/savings-plans/{plan_id}/execute?current_price=<float>` | Sparplan ausführen (legt Position bei Bedarf an; `current_price>0` erforderlich) |
| POST | `/import` | Einmaliger Import aus Legacy-`localStorage`. Body: `{ positions:[…], transactions:[…] }`. Nur in leere DB. |

## Quotes (`/api/quotes`) – Finnhub

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/{ticker}` | Aktueller Kurs → `{ ticker, current_price, day_change, previous_close }` |
| GET | `/batch/quotes?tickers=AAPL,MSFT,VOO` | Mehrere Kurse auf einmal (max. 50) → `{ TICKER: { current_price, day_change, previous_close } }` |

## Marktdaten (`/api/market-data`) – yfinance + Finnhub (gecacht)

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/history/{ticker}?period=1y` | Historische OHLCV-Tageskurse (Cache → yfinance). `period`: 1mo,3mo,6mo,1y,2y,5y |
| GET | `/fundamentals/{ticker}` | KGV, Marktkap., EPS, Umsatzwachstum, 52W-Hoch/Tief, Dividende, Beta (Cache, TTL 12 h) |
| GET | `/news/{ticker}?days=7` | News inkl. Sentiment (Cache, TTL 1 h, Dedup nach URL). `days` ≤ 30 |
| POST | `/warmup` | Cacht Preise/Fundamentaldaten/News für **alle** Portfolio-Ticker vor (force-Refresh). Für die Demo. |

## Agent (`/api/agent`)

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/analyze/{ticker}?current_prices=<json>&agentic=false` | **SSE-Stream** Einzelanalyse. Liefert: deterministischen Block → (optional Tool-Aufrufe bei `agentic=true`) → **Evidence-gegate** Begründung. Endet mit `data: [DONE]`. |
| GET | `/analyze-portfolio?current_prices=<json>` | **SSE-Stream** Portfolio-Analyse (Ensemble je Position + LLM-Zusammenfassung) |
| GET | `/chat?question=<text>&current_prices=<json>` | **SSE-Stream** Freitext-Chat mit Tool-Agent |
| GET | `/news-summary/{ticker}` | **SSE-Stream** News-Zusammenfassung (Themen + Risiken) |
| GET | `/rebalance?current_prices=<json>` | **SSE-Stream** Diversifikations-/Rebalancing-Vorschläge |
| GET | `/status` | `{ ollama_reachable, model, model_available, available_models }` |
| POST | `/pull-model` | Zieht das konfigurierte Modell; streamt den Fortschritt als SSE |

## Eval (`/api/eval`) — v2.0-baseline

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/metrics` | Aggregat + letzte 50 Analyse-Runs (`faithful_rate`, Latenz, Tokens/s) |
| GET | `/backtest?horizon=20&step=5&tickers=AAPL,MSFT` | Walk-Forward-Backtest des Ensembles. Leere `tickers` = alle Portfolio-Positionen |

### SSE-Format
Jede Nachricht ist eine Zeile `data: <text>\n\n`. Zeilenumbrüche im Inhalt sind als `\n` escaped
(Client wandelt zurück). Stream-Ende: `data: [DONE]`. Fehler: `data: [FEHLER: …]`.

> **Hinweis:** Die Analyse-Endpunkte sind absichtlich **GET** (Browser-`EventSource` kann nur GET) und
> öffnen ihre DB-Session im Stream-Generator. Siehe ADR-04 in
> [07-entscheidungslog.md](07-entscheidungslog.md).

## Screener (`/api/screener`) — Alt-B Schicht 2 (nur `feature/alt-b`)

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/alt-b/latest` | Letzter persistierter Scan (`screener_runs`), sofort verfügbar. Leere Antwort (`created_at: null`), wenn noch nie gescannt |
| GET | `/alt-b/scan?limit=12&min_score=0` | **SSE**: gestufter Scan (Fundamentals → EDGAR-Vorprüfung → Detail + LLM). Fortschritts-Events `{stage, i, n, ticker}`, dann `{result: <ScreenerResponse>}`; Ergebnis wird in der DB gecacht |
| GET | `/universe` | Universum-Status: `{count, updated_at, source: "live"\|"kuratiert"}` |
| GET | `/universe/refresh?limit=` | **SSE**: NASDAQ-Biotech-Universum neu crawlen (Finnhub, ~50 min Free-Tier). `limit` begrenzt die geprüften Symbole (Demo) |

Scan-Funnel: Universum (gecrawlt oder kuratierte JSON) → Market Cap ≤ 15 Mrd. → Umsatz ok
(inkl. Pre-Revenue) → EDGAR-Vorprüfung (8-K-Katalysator/Form 4, 7 Tage, EIN submissions-Call) →
Detail (Finnhub-News/-Insider, 8-K-Pressetexte) + LLM-Klassifikation (Typ vom LLM, Stärke aus der
Rubrik, Beleg-Zitat-Pflicht; Regex-Fallback ohne Ollama) → Score ≥ `min_score`.

## CORS

`main.py` erlaubt Origins `http://localhost:5173`, `:3000`, `:8080` (Vite-Dev-Server). Bei anderen
Frontend-Ports dort ergänzen.
