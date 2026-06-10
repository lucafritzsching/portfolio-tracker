# Alt-B Schicht 2 — Design: Volles Universum + SEC-8-K + LLM-Story-Erkennung

Datum: 2026-06-10 · Branch: `feature/alt-b` · Status: umgesetzt

## Problem

Die Alt-B-Idee (NASDAQ-Biotech ≤ 15 Mrd. Market Cap, Umsatz-Kriterium, Events der letzten
7 Tage: Turnaround-Story / Insider-Käufe / News) fand in Schicht 1 kaum Treffer:

1. **Zu eng:** statisches 10-Ticker-Universum; hartes „Umsatzwachstum > 0" warf
   Pre-Revenue-Biotechs (die Mehrheit des Sektors) raus.
2. **Zu primitiv:** „Turnaround-Story" = Regex auf einzelne Finnhub-Headlines; die News-API
   ist lückenhaft.

## Entscheidungen (mit dem User abgestimmt)

| Frage | Entscheidung |
|---|---|
| Story-Erkennung | SEC-8-K + News als Rohmaterial; **LLM (qwen3:14b) bestimmt Typ + Story, Stärke-Skala bleibt deterministisch im Code** |
| Laufzeit | **Button-Scan mit SSE-Fortschritt, Ergebnis in DB gecacht** (`screener_runs`); View zeigt sofort den letzten Stand |
| Umsatzfilter | **Pre-Revenue ok** — nur schrumpfender Umsatz fällt raus; Wachstum > 0 gibt 20 Bonuspunkte |

## Architektur

```
screener_universe (DB-Cache, Finnhub-Crawl ~250 Ticker, manueller Refresh ~50 min)
  │ 1. Fundamentals (yfinance, gecacht): Market Cap ≤ 15 Mrd.
  │ 2. Umsatz: > 0 ODER None (Pre-Revenue)
  │ 3. EDGAR-Vorprüfung: EIN submissions-Call/Ticker → 8-K-Katalysator ODER Form 4 (7 Tage)
  │ 4. Detail nur für Treffer: Finnhub-News/-Insider, 8-K-Pressetexte (EX-99.1)
  │ 5. LLM-Klassifikation (Typ aus EVENT_RUBRIC + Story + Beleg-Zitat), Regex-Fallback
  │ 6. Score: Katalysator 0–50 · Insider 0–30 · Umsatz-Bonus 0–20; Gate: Stärke ≥ 3 ODER Insider ≥ 50k$
  ▼
screener_runs (payload = komplette Screener-Antwort als JSON)
```

**LLM-Guardrails** (`backend/services/event_llm.py`): `event_type` muss exakt in
`event_strength.EVENT_RUBRIC` liegen (Code mappt Typ → Stärke 0–5); `evidence_quote` muss
wörtlich im Quelltext stehen; jeder Fehler → deterministischer Regex-Fallback. Der Scan
bricht nie wegen des LLM ab.

## Komponenten

| Baustein | Datei |
|---|---|
| Scan-Pipeline + Scoring + Persistenz | `backend/services/screener.py` (`run_alt_b_scan`, `score_alt_b`) |
| LLM-Klassifikation | `backend/services/event_llm.py` |
| Stärke-Rubrik + Regex-Klassifikation | `backend/services/event_strength.py` (`EVENT_RUBRIC`) |
| EDGAR 8-K/Form-4 | `backend/services/sec_filings.py` (`parse_recent_signals`, `fetch_8k_catalysts`) |
| Universum-Crawl + Persistenz | `backend/services/universe.py` |
| DB-Modelle | `backend/models.py` (`ScreenerUniverse`, `ScreenerRun`) |
| API | `backend/routers/screener.py` (`/alt-b/scan` SSE, `/alt-b/latest`, `/universe`, `/universe/refresh` SSE) |
| UI | `frontend/src/views/ScreenerView.vue` (Scan-Button, Live-Fortschritt, LLM-Story + Beleg, 8-K-Links) |

## Tests

`backend/tests/`: `test_event_llm.py` (Guardrails/Fallback, Fake-Ollama),
`test_scan_pipeline.py` (Funnel-Zähler, alles gestubbt), `test_sec_filings.py`
(Form-4-Vorprüfung), `test_alt_b_scoring.py` (Pre-Revenue, LLM-/8-K-Katalysator).

## Bewusst nicht gebaut

- Backtest-Integration (Schicht 3, `backend/services/backtest.py` liegt bereit).
- Nächtlicher Scheduler — manueller Button reicht.
- Alt-A unverändert (läuft als Zweit-Score mit).

Siehe auch ADR-14 in [07-entscheidungslog.md](../../07-entscheidungslog.md).
