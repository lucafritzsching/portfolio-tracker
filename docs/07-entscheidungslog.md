# 7. Entscheidungslog (ADRs)

Chronologische Architektur-Entscheidungen mit Begründung. Format je Eintrag:
**Kontext → Entscheidung → Begründung → Konsequenz.**

---

## ADR-01 – Neubau als Full-Stack-App statt Prototyp-Erweiterung
**Kontext:** Der Ausgangsstand war ein einzelnes `index.html` (HTML/CSS/JS, `localStorage`) – ein
Prototyp. Ziel ist eine produktionsnahe App mit lokalem KI-Agenten.
**Entscheidung:** Kompletter Neubau: Vue 3 + TypeScript (Frontend), FastAPI (Backend),
PostgreSQL (DB), Ollama (LLM). Kein Migrationsaufwand außer optionalem Datenimport.
**Begründung:** Data Science braucht Python; der Agent braucht serverseitige Orchestrierung +
Streaming; `localStorage` ist für dauerhafte Historie ungeeignet.
**Konsequenz:** Klare Schichtentrennung; der Prototyp bleibt nur als Referenz (`index.html`).

## ADR-02 – PostgreSQL statt SQLite
**Kontext:** Single-User-App auf einem Laptop; Datenmengen klein.
**Entscheidung:** PostgreSQL (in Docker).
**Begründung:** Persistenter Cache für Kurszeitreihen/News, „production"-Optik fürs Uni-Projekt,
Docker läuft ohnehin für Ollama.
**Konsequenz / Trade-off:** Bewusst überdimensioniert – SQLite hätte genügt. Akzeptiert wegen
Optik und geringem Zusatzaufwand. (Dokumentiert als verteidigbarer Trade-off.)

## ADR-03 – FastAPI als Backend
**Kontext:** Brauchen DS-Bibliotheken (pandas/sklearn/statsmodels/yfinance) und SSE-Streaming.
**Entscheidung:** Python + FastAPI.
**Begründung:** Beste DS-Integration + erstklassiges async/`StreamingResponse`.
**Konsequenz:** Agent-Streaming und ML laufen im selben Stack.

## ADR-04 – Agent-Streaming via SSE/EventSource ⇒ GET-Endpunkte + eigene DB-Session
**Kontext:** Die Analyse soll token-weise im Browser erscheinen.
**Entscheidung:** Server-Sent Events; Browser nutzt `EventSource`. Die Agent-Endpunkte sind **GET**,
und die DB-Session wird **innerhalb des Stream-Generators** geöffnet.
**Begründung:** `EventSource` kann nur GET. Eine `Depends(get_db)`-Session würde beim Rückkehren des
Handlers geschlossen – also bevor der Stream den Body sendet.
**Konsequenz:** `routers/agent.py` nutzt `async with AsyncSessionLocal()`. (Frühere POST-Variante war
inkompatibel mit EventSource → behoben.)

## ADR-05 – Vollverkauf behält die Position (`shares = 0`) statt sie zu löschen
**Kontext:** `Position`⇄`Transaction` hat eine Lösch-Kaskade.
**Entscheidung:** Beim Verkauf der letzten Anteile wird die Position auf `shares = 0` gesetzt, nicht
gelöscht.
**Begründung:** Ein Löschen würde per Kaskade die gesamte Transaktionshistorie (inkl. realisiertem
P&L) mitlöschen und die Langzeit-Nachvollziehbarkeit zerstören.
**Konsequenz:** Historie bleibt erhalten; geschlossene Positionen haben `shares = 0`.

## ADR-06 – Modell-Upgrade Qwen 2.5 7B → 14B
**Kontext:** Demo-Laptop ist Apple Silicon mit ≥16 GB RAM.
**Entscheidung:** Standardmodell `qwen2.5:14b`; `qwen2.5:7b` als Low-RAM-Fallback.
**Begründung:** 14B (~9 GB q4) bietet deutlich bessere Reasoning-/Tool-Calling-/Deutsch-Qualität und
läuft auf 16 GB flüssig.
**Konsequenz:** Konfigurierbar über `OLLAMA_MODEL` in `backend/.env`.

## ADR-07 – Hybrid-Agent: deterministische Entscheidung, LLM erklärt
**Kontext:** Ein autonom entscheidendes 7B/14B-LLM ist unzuverlässig und **nicht reproduzierbar**.
**Entscheidung:** Die Empfehlung kommt aus `compute_ensemble` (reine Funktion). Das LLM untersucht
(Tool-Calling) und **begründet** die Entscheidung, überschreibt sie aber nie.
**Begründung:** Reproduzierbarkeit + Nachvollziehbarkeit (akademisch verteidigbar) bei gleichzeitiger
„Agenten"-Optik. Siehe [03-agent-design.md](03-agent-design.md).
**Konsequenz:** 4-Phasen-Ablauf; klar getrennte Verantwortlichkeiten (Pipeline vs. LLM).

## ADR-08 – Eine geteilte Datenquelle + nicht-blockierendes I/O
**Kontext:** yfinance/Finnhub-Abrufe waren teils in Routern *und* im Agenten dupliziert und liefen
blockierend im Event-Loop.
**Entscheidung:** Aller Abruf+Cache in `services/market_data.py`; alle yfinance-Aufrufe via
`asyncio.to_thread`. Pro-Analyse-Cache im `ToolExecutor`.
**Begründung:** Eine Datenquelle/ein Cache; der Event-Loop blockiert nicht während mehrsekündiger
Netzabrufe.
**Konsequenz:** Router und Agent rufen dieselben Funktionen; Freshness-Regeln zentral.

## ADR-09 – News-Sentiment per LLM-Aggregat statt Keyword-Zählung
**Kontext:** Ursprüngliches Sentiment war reine Keyword-Zählung – schwach.
**Entscheidung:** Ein LLM-Aggregataufruf (`agent/sentiment.py`, Temperatur 0) liefert einen
Sentiment-Score; Keyword-Variante bleibt Offline-Fallback.
**Begründung:** Bessere Qualität ohne schwere Abhängigkeit (kein FinBERT/torch).
**Konsequenz:** Sentiment fließt als gewichtete Komponente (0.15) ins Ensemble.

## ADR-10 – Dependency-Hygiene
**Kontext:** `pandas-ta` war ungenutzt (Indikatoren sind handgerechnet) und inkompatibel mit numpy 2;
`vue-router` war ungenutzt (Views laufen über den `ui`-Store).
**Entscheidung:** Beide entfernt; toter Scaffold-Code gelöscht.
**Begründung:** Weniger Angriffsfläche, schlankere Builds, klarere Codebasis.
**Konsequenz:** Indikatoren bleiben in `data_science.py` selbst implementiert.

## ADR-11 – Evidence-Katalog + Faithfulness-Gate gegen LLM-Halluzinationen (v2.0-baseline)
**Kontext:** Das lokale Modell (`qwen3:14b`) erfindet in der Erklärungsschicht Kurse, RSI-Werte und
Prozente, obwohl die Pipeline korrekte Zahlen liefert. Prompt-Regeln allein reichen nicht.
**Entscheidung:** Vor dem LLM-Aufruf wird ein **Evidence-Katalog** aus Pipeline-Daten gebaut
(`agent/evidence.py`). Das LLM referenziert Zahlen nur als `{{ev:id}}`. Nach der Antwort prüft
`eval/faithfulness.py` jeden Satz und entfernt ungedeckte Aussagen. Bei fehlenden Kursdaten: **NO_DATA**
ohne LLM-Call.
**Begründung:** Die Entscheidung bleibt deterministisch; das Risiko liegt nur in der Erklärung.
Gate + Platzhalter machen Halluzinationen für die Demo nachweisbar reduzierbar (`AnalysisMetric.faithful`).
**Konsequenz / Trade-off:** Erklärung wird non-stream geholten, dann gegated und in Chunks gesendet
(kurzer Delay statt Live-Tokens). Chat/Portfolio/Rebalance haben das Gate noch nicht.
**Details:** [09-release-v2.0-baseline.md](09-release-v2.0-baseline.md)

## ADR-12 – Git-Branching für parallele Strategie-Teams (v2.0-baseline)
**Kontext:** Zwei Gruppen testen unterschiedliche Investment-Strategien (Alt A: deterministisch/Bollinger;
Alt B: News-Narrativ) auf derselben Codebasis.
**Entscheidung:** Ein Repo, vier Branches: `main` (stabil), `develop` (Integration),
`feature/strategy-alt-a`, `feature/strategy-alt-b`. Tag `v2.0-baseline` auf `main`.
**Begründung:** Kein doppeltes Setup/CI; gemeinsame Baseline-Fixes zentral, Strategie-Code isoliert.
**Konsequenz:** Strategie-Module (Screener, Insider, …) nur in Feature-Branches, nicht in `main`.

## ADR-13 – Alt-B als event-basiertes, ehrliches Turnaround-Screening (Schicht 1)
**Kontext:** Der erste Alt-B-Screener qualifizierte über „positive News ODER Insider" und bewertete
News per Substring-Keyword – anfällig für Fehltreffer, fehlende Richtungserkennung und Fehlalarme bei
hochgelaufenen Titeln oder Routine-/Recap-Meldungen. Eine harte Umsatz-Pflicht (`revenue_growth > 0`)
schloss zudem Pre-Revenue-Biotechs aus, und der als „GenAI" gelabelte Block war reine Keyword-Logik.
**Entscheidung:** Deterministischer Umbau in `services/event_strength.py` (rein, unit-getestet):
- **Ereignis-Stärke 1–5**, nur ≥ 3 qualifiziert; Klassifikation per **Wortgrenzen-Regex** (kein
  Substring) mit **Richtungs-/Negationserkennung** und **Quellen-Gating** (Firmen-PR = volle Stärke,
  reine Kommentar-/Recap-Quellen gedeckelt).
- **Relevanz-Filter** (nur ticker-/firmenspezifische News).
- **Schwäche-/Setup-Gate** (ausgebombt + überverkauft) als Pflicht für „Turnaround".
- **Gate = Setup UND Katalysator ≥ 3 UND kein Sektor-Abwärtstrend (XBI)**, danach Konfidenz-Stufen
  mit ehrlichen Labels.
- **Pre-Revenue-Fallback** im Basisfilter (kein Umsatz = ok, nur schrumpfender Umsatz fällt raus).
**Begründung:** Ereignis-*Qualität* statt -Stimmung; Stärke + Setup + Recency zusammen verhindern die
Fehlalarme. Alles bleibt deterministisch und über `decision_log`/`score_breakdown` erklärbar. Die
Stärke-**Skala** bleibt menschlich im Code – ein LLM darf später nur den *Typ* klassifizieren; erst
damit wird „GenAI" ehrlich.
**Konsequenz / Trade-off:** Offen (Schicht 2–4): Live-/dynamisches Universum, Sektor aus Live-Quelle,
SEC-8-K-Ereignis-Rückgrat, LLM-Stärke-Klassifikation und ein Backtest als Wirksamkeitsnachweis.
Strategie-Code nur auf `feature/alt-b`.

## ADR-14 – Alt-B Schicht 2: volles Universum, SEC-8-K-Rückgrat, LLM-Typ + Button-Scan mit Cache
**Kontext:** Schicht 1 fand kaum Treffer (statisches 10-Ticker-Universum, harte Umsatz-Pflicht) und
erkannte „Turnaround-Stories" nur per Regex auf einzelne, lückenhafte News-Headlines.
**Entscheidung:**
- **Dynamisches Universum:** Finnhub-Crawl (NASDAQ → Biotech → ≤ 15 Mrd., ~250 Ticker) in
  `screener_universe` gecacht; Refresh manuell per Button (~50 min Free-Tier). Ohne Crawl Fallback
  auf die kuratierte JSON — die App bleibt sofort benutzbar.
- **EDGAR-Vorprüfung statt Finnhub-Breitenscan:** EIN `submissions`-Call je Ticker liefert 8-K
  (Katalysator-Items 1.01/7.01/8.01) **und** Form 4 im 7-Tage-Fenster. Rate-limitierte
  Finnhub-Calls (News/Insider) nur noch für diese Treffer → Scan in Minuten statt Stunden.
- **LLM bestimmt Typ, Code setzt Skala** (löst das ADR-13-Versprechen ein): qwen3:14b klassifiziert
  8-K-Pressetexte + relevante News auf einen Typ aus `EVENT_RUBRIC` plus deutsche Story; Stärke 0–5
  kommt deterministisch aus der Rubrik. Guardrails: Typ muss in der Rubrik liegen, Beleg-Zitat muss
  wörtlich im Quelltext stehen, jeder Fehler → Regex-Fallback (`event_llm.py`, unit-getestet).
- **Button-Scan + SSE + DB-Cache:** `GET /screener/alt-b/scan` streamt Fortschritt, Ergebnis liegt
  als JSON-Snapshot in `screener_runs`; `GET /alt-b/latest` lädt ihn sofort. Kein Live-GET mehr.
- **Pre-Revenue-Fallback wiederhergestellt** (war zwischenzeitlich auf `> 0` verschärft): kein
  Umsatz = zulässig ohne Bonuspunkte, nur schrumpfender Umsatz fällt raus.
**Begründung:** Mehr ehrliche Treffer durch Breite (Universum, Pre-Revenue) statt durch laschere
Kriterien; 8-K ist lückenlos und point-in-time; das LLM liefert die Story, halluziniert aber keine
Stärke und keine Belege.
**Konsequenz / Trade-off:** Scan dauert Minuten (bewusst: Button + Fortschritt statt Latenz-Lüge);
Universum-Crawl bleibt manuell. Offen (Schicht 3): Backtest-Integration als Wirksamkeitsnachweis.

## ADR-15 – Alt-B Schicht 3–4: hybrider NL-Ziel-Klassifikator + Trace + eigene UI-Sektion
**Kontext:** ADR-13 ließ bewusst offen, dass ein LLM später Bedeutung/Typ klassifizieren soll. Zudem
stellte sich heraus: Forschungsgegenstand ist **nicht das Biotech-Screening**, sondern **wie gut ein
lokales LLM Freitext in gute Outputs übersetzt** – der hartcodierte Biotech-Screener war nur eine
Engpass-Vermeidung.
**Entscheidung:**
- **Konfigurierbares NL-Ziel** (`services/nl_target.py`): ein Freitext-*Kriterium* (NICHT auf „Turnaround"
  hartcodiert) wird gegen die News einer Aktie beurteilt. Pipeline: günstiger Regex-Prefilter
  (`event_strength`: Relevanz + Negation + Materialität) → **ein** gebündelter LLM-Aufruf → Urteil.
- **Anti-Halluzination:** LLM-Stärke wird auf **Regex-Basis ±1** geklammert (das LLM darf nuancieren, aber
  keinen Katalysator erfinden, den der Prefilter ablehnt); Belege müssen reale Schlagzeilen-Indizes sein;
  bei LLM-Ausfall **deterministischer Regex-Fallback** (kein Regress).
- **Zwei Modi:** `fast` (1 Aufruf) vs. `agentic` (kleiner, entkoppelter Tool-Loop mit `inspect_headline`,
  das die deterministische Klassifikation pro Schlagzeile offenlegt) – für den Achse-B-Vergleich.
- **Decision-Trace** (`services/trace.py`) macht jeden Schritt nachvollziehbar (`duration_ms` lokalisiert
  später den Compute-Engpass). **Eigene UI-Sektion „NL-Agent"** (`views/AltBView.vue` +
  `GET /api/agent/nl-target`), getrennt vom KI-Chat-Bereich (Team Alt-A) und vom Alt-B-Scanner.
**Begründung:** Determinismus bleibt das Rückgrat (Gate/Stärke-Skala in Code); das LLM liefert NL-Urteil +
Begründung, bounded gegen Halluzination – analog zum Evidence-/Faithfulness-Ansatz (ADR-11). „GenAI" wird
ehrlich messbar: Regex-Basis vs. LLM-Rohstärke stehen im Trace.
**Konsequenz / Trade-off:** `nl_target` ist entkoppelt (nur `event_strength` + `config` + `httpx`) und
bewusst NICHT in `score_alt_b` verdrahtet (Freitext→Output ist das Ziel, nicht der Sektor-Scan). Offen:
Reddit/weitere NL-Quellen hinter `NLItem`, Multi-Agent-Orchestrierung, ein Backtest. Details:
[10-experiment-alt-b.md](10-experiment-alt-b.md).

---

## Behobene Bugs aus dem Code-Review (Baseline)

Vor dem Agenten-Umbau wurde die erste Implementierung reviewt. Wichtige korrigierte Fehler (erklärt,
warum der Code heute so aussieht):

| Fehler | Wirkung | Fix |
|---|---|---|
| `Position(**model_dump(), ticker=…)` doppeltes `ticker`-kwarg | jede Positionsanlage warf `TypeError` (500) | Dump kopieren, `ticker` darin setzen |
| Agent-Endpunkte als POST, Frontend nutzt `EventSource` (GET) | Analyse startete nie (405) | Endpunkte auf GET (ADR-04) |
| `day_pnl += (current ?? 0 - prev)` (Operator-Präzedenz) | Tages-P&L = ganzer Positionswert | korrekt geklammert: `((current ?? 0) - prev)` |
| `portfolio_weight` über 1-Element-Liste | immer ~100 % | Summe über **alle** Positionen |
| Sparplan-Ausführung ohne Position | FK-Verletzung (500) | Position bei Bedarf anlegen + `price > 0` prüfen |
| blockierende yfinance-Aufrufe im async-Pfad | Event-Loop friert ein | `asyncio.to_thread` (ADR-08) |

## Architektur-Verifikation (mit stärkerem Modell)

Vor dem Umbau wurde die Architektur gezielt geprüft (Frage: „Ist das der beste Ansatz für den Use
Case?"). Ergebnis: Stack bestätigt; einzige Paradigmen-Änderung = **Hybrid-Agent** (ADR-07), plus
14B-Upgrade (ADR-06), Vorab-Cache (Warmup), LLM-Sentiment (ADR-09) und echtes Streaming.
