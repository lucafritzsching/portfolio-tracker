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

## ADR-14 – Alt-B Schicht 2–4: hybrider NL-Ziel-Klassifikator + Trace + eigene UI-Sektion
**Kontext:** ADR-13 ließ bewusst offen, dass ein LLM später Bedeutung/Typ klassifizieren soll. Zudem
stellte sich heraus: Forschungsgegenstand ist **nicht das Biotech-Screening**, sondern **wie gut ein
lokales LLM Freitext in gute Outputs übersetzt** – der hartcodierte Biotech-Screener war nur eine
Engpass-Vermeidung (und ist nicht einmal in `main.py` gemountet).
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
  später den Compute-Engpass). **Eigene UI-Sektion „Alt B"** (`views/AltBView.vue` + `GET /api/agent/nl-target`),
  getrennt vom KI-Chat-Bereich (Team Alt-A) – gespiegelt, plus Alt-B-Extras (Trace, fast/agentic).
**Begründung:** Determinismus bleibt das Rückgrat (Gate/Stärke-Skala in Code); das LLM liefert NL-Urteil +
Begründung, bounded gegen Halluzination – analog zum Evidence-/Faithfulness-Ansatz (ADR-11). „GenAI" wird
ehrlich messbar: Regex-Basis vs. LLM-Rohstärke stehen im Trace.
**Konsequenz / Trade-off:** `nl_target` ist entkoppelt (nur `event_strength` + `config` + `httpx`) und
bewusst NICHT in `score_alt_b` verdrahtet (Freitext→Output ist das Ziel, nicht der Sektor-Scan). Offen:
Reddit/weitere NL-Quellen hinter `NLItem`, Multi-Agent-Orchestrierung, ein Backtest. Details:
[10-experiment-alt-b.md](10-experiment-alt-b.md).

## ADR-15 – Demo: Alt A vs. Alt B vergleichbar (zwei Fenster) + Strategie-Finder + Determinismus-vs-LLM gemessen
**Kontext:** Für die Präsentation sollen **beide** Alternativen verglichen/erklärt und die Wochenarbeit
gezeigt werden – **ohne** die Logik zu konsolidieren, **ohne** Alt A zu verändern, minimal und demo-stabil
(LLM ist der Compute-Flaschenhals, nicht ARIMA/RF=CPU). Erkenntnis: die Modus-Achse „1 LLM-Call vs.
Tool-Calling-Agent" existiert in **beiden** bereits (Alt-A `agentic`-Flag; Alt-B `mode` fast/agentic) –
es fehlte nur eine **Gegenüberstellung**.
**Entscheidung:**
- **Strategie-Finder** als Alt-B-*Discovery* (`services/finder.py`, `agent/finder_runner.py`,
  `GET /api/agent/finder`, AltBView-Tab): Freitext-*Mandat* → LLM-Parse (im Trace sichtbar) →
  **deterministischer** `yf.screen` (yfinance 1.4.1, serverseitig) → NL-Agent (`evaluate_nl_target`)
  **nur** auf die Top-N Überlebenden → Rangliste + Trace. Bounded (1 Screen-Call + gedeckelte LLM-Calls),
  Fallback-Universum bei Yahoo-Ausfall. Kein Eingriff in Alt A.
- **Vergleichs-View** (`views/ComparisonView.vue`, rein Frontend): EIN Input (Ticker + NL-Kriterium) →
  **zwei Spalten**, die die **bestehenden** Endpoints aufrufen (`/agent/analyze/{ticker}`,
  `/agent/nl-target`): links Alt-A (Code entscheidet, LLM erklärt, Evidence-Gate) neben rechts Alt-B
  (LLM beurteilt, regex-Clamp). Je Spalte Toggle 1-Call ↔ Tool-Agent. **Bewusst keine Logik-Konsolidierung.**
- **Determinismus-vs-LLM gemessen** (read-only): agentic 89 % vs. fast 78 %; geführt (Clamp) 81 % vs. pur
  78 % bei 0 vs. 2 False-Positives; `think:false`/`true` → Latenz 4–10×, gleiches Kern-Urteil. Belege:
  [evidence/determinismus_vs_llm.md](evidence/determinismus_vs_llm.md), [think_mode_findings.md](evidence/think_mode_findings.md).
**Begründung:** maximale Vergleichbarkeit/Erklärkraft bei **minimalem Risiko** (echte Pipelines, Alt A
unangetastet). Die deterministischen Leitplanken (Ensemble/Evidence bei A, Clamp/Prefilter bei B) tragen
die Qualität **messbar** mit – die Kernthese beider Alternativen.
**Konsequenz / Trade-off:** Multi-Agent bleibt **Ausblick** (nicht gebaut); der Finder wird **nicht** mit
Alt-As Ensemble verdrahtet (das wäre Konsolidierung); `think:false` ist Default (Fix `cc4e2e9`). Eval-Zahlen
stammen von **vor** dem think-Fix → Re-Run offen. Der regex-Guard ist nicht gratis (unterdrückte 1 korrektes
Urteil, da die `event_strength`-Rubrik biotech-getunt ist).

## ADR-16 – Ein Chat-Router-Agent ersetzt die getrennten Agenten-Oberflächen
**Kontext:** Drei zerfaserte Agenten-Oberflächen (KI-Analyse, Alt-B-Finder/NL, Vergleich); zwei liefen in
Fehler **ohne Server-Log** (in den SSE-`[FEHLER]`-String geschluckt). Wunsch: drastisch einfacher.
**Entscheidung:** **EIN Chat-Fenster.** `orchestrator.ask_stream` routet eine Freitext-Anfrage per **nativem
Ollama-Tool-Calling** (`_run_agent_loop`, T=0, sichtbare 🔧-Trace) an Werkzeuge: `screen_by_strategy`
(yfinance-Screen), `judge_news` (NL-Urteil), `run_statistical_model`/`calculate_technical_indicators`
(ARIMA/RF/Technik) + Hintergrund-Tools. Endpoint `GET /api/agent/ask`. Frontend: `ChatView` = einzige
Agenten-Oberfläche (mit Status/Warmup/Modell-Controls); `AnalysisView`/`AltBView`/`ComparisonView` +
`finder_runner`/`nl_target_runner` + `/agent/finder`+`/agent/nl-target` **entfernt**. **Durchgehendes
Logging** (Tool-Calls, Tracebacks via `logger.exception`, SSE-Fehler) statt stummem Schlucken.
**Begründung:** Das Routing-Substrat existierte bereits; LLM-Tool-Calling genügt (kein separater
Intent-Klassifikator); die Tools sind deterministisch/guarded → sicher. Der Vergleich „deterministisch vs.
LLM" lebt nun **im Agenten** (Statistik-Tools vs. NL-Urteil) + in Flowchart 8/Doku — **keine** Konsolidierung
zu einem Score.
**Konsequenz / Trade-off:** Multi-Agent bleibt Ausblick. Das schwere Evidence-/Faithfulness-Gate der
Alt-A-Analyse wird im Chat nicht angewandt; Erdung über Tool-Ergebnisse + Prompt-Disziplin + NL-Belegbindung
+ Logging.

## ADR-17 – Generischer, beleggebundener NL-Judge + ehrliche, validierte DS-Modelle
**Kontext:** (1) Der NL-Judge war **biotech-getunt** (`event_strength`-Rubrik + Regex-Clamp) → für
Nicht-Biotech-Titel praktisch stumm. (2) Die DS-Modelle waren methodisch fragwürdig: ARIMA-„Konfidenz"
`1−|AIC|/10000` (sinnlos), RandomForest sagte einen **~20 Tage alten** Bar vorher, **keine**
Out-of-Sample-Validierung, **keine** Persistenz.
**Entscheidung (NL):** `services/nl_target.py` neu — **Relevanz** (Ticker/Name) + **Subjekt-Fokus-Prompt** +
**Belegbindung** (`build_verdict` statt `combine_verdict`): ein „Treffer" braucht ≥ 1 zitierte **echte**
Schlagzeile; **kein** Clamp, **keine** Sektor-Rubrik. Vollständig sektor-agnostisch.
**Entscheidung (DS):** ARIMA-Konfidenz aus dem **95 %-Prognoseintervall**; RandomForest sagt den
**aktuellen** Bar vorher + weist **Out-of-Sample-Genauigkeit** (zeitgeordneter Holdout) aus + robuste
Klassenwahrscheinlichkeiten. Befunde **ehrlich dokumentiert** ([12-data-science-methodik.md](12-data-science-methodik.md)):
RF-OOS ≈ 51 %, Walk-Forward-Backtest **ohne verlässlichen Vorteil**, keine Persistenz (Refit pro Anfrage).
**Begründung:** Es ist ein **Data-Science-Projekt** — Allgemeingültigkeit + methodische Ehrlichkeit zählen
mehr als Feature-Zahl oder Schein-Genauigkeit. Anti-Halluzination jetzt über **Erdung** (das LLM kann keine
erfundene Schlagzeile zitieren) statt einer sektorspezifischen Heuristik.
**Konsequenz / Trade-off:** Der frühere „0 Halluzinationen via Clamp"-Beleg ist durch Belegbindung abgelöst;
News-Feeds bleiben verrauscht (tangentiale Erwähnungen möglich, durch Relevanz + Fokus gemindert). Ausblick:
`auto_arima`, RF mit `TimeSeriesSplit`-CV + persistiertem Modell, größeres Backtest-Universum.

## ADR-18 – Baselines überall, purged Split, zwei neue Chat-Tools, Cache-Härtung
**Kontext:** Bewertungskriterium der Abschlusspräsentation: Modelle **und** Trading-Mechanismus müssen
gegen **sinnvolle Baselines** verglichen werden. Zudem vier Robustheits-Defekte: (1) die finale
Agent-Antwort wurde **doppelt generiert** (Loop-Ergebnis verworfen, zweiter Ollama-Call → ~2× Latenz der
Schlussphase); (2) ein Refresh mit kurzem Zeitraum (LLM-gewähltes `period="1mo"`) **löschte die
2y-Kurshistorie** (delete+insert) und ließ die Statistik-Modelle verhungern; (3) der News-Cache maß
Frische am `published_at` des neuesten Artikels (< 1 h praktisch nie wahr) → **jeder Aufruf refetchte
Finnhub**; (4) redundante `yf.info`-Calls pro Lauf. Außerdem trainierte der RF die letzten 20 Zeilen
(Zukunft unbekannt) still als Default-HOLD mit.
**Entscheidung (DS-Baselines):** Jede Modell-Ebene bekommt ihren Maßstab: **RF** Holdout-Accuracy vs.
**Mehrheitsklassen-Baseline** (purged Holdout mit 20-Tage-Gap = Label-Horizont gegen Label-Leakage,
`class_weight="balanced"`, Label-Fix); **ARIMA** 30T-Holdout-MAE vs. **naive Random-Walk-Baseline**
(opt-in `validate=True`, nur im Statistik-Tool/Quick-Stats — der Backtest bliebe sonst ~2× langsamer);
**Backtest** je Signal vs. **Buy&Hold-Basisrate aller Fenster** (`baseline`-Zeile, pure Funktion
`backtest_prices` via `to_thread`).
**Entscheidung (Tools):** Zwei neue Werkzeuge im Router-Loop: **`run_backtest(ticker)`** (historische
Signal-Güte im Chat, step=10) und **`discover_news_movers(direction, criterion?)`** — die ticker-freie
News-Discovery aus dem Ausblick von [00-gesamtanalyse.md](00-gesamtanalyse.md): deterministischer
Yahoo-Mover-Screen (day_gainers/losers/most_actives) liefert Kandidaten, dann urteilt der beleggebundene
NL-Judge über deren News (max. 5 Kandidaten ans LLM, Rest als `weitere_ticker_ungeprueft` ausgewiesen).
**Entscheidung (Robustheit):** Finale Antwort direkt aus dem Loop-Response (chunked, kein zweiter Call);
Preis-Downloads nie kürzer als 2y (Superset); News-TTL über prozess-lokalen Fetch-Timestamp (NewsCache
hat keine `fetched_at`-Spalte, keine Migrationen — Neustart kostet einen Refetch je Ticker); ein
gemeinsamer `_yf_info`-Cache pro Lauf.
**Begründung:** Baselines machen die „ehrliche DS"-Linie (ADR-17) messbar statt nur erzählbar; die neuen
Tools nutzen ausschließlich vorhandene, getestete Bausteine (Backtest-Modul, NL-Judge, Screen-Infrastruktur)
— deterministische Quelle → LLM-Urteil bleibt das Grundmuster.
**Konsequenz / Trade-off:** `class_weight="balanced"` **verschiebt Live-RF-Signale** (weniger
Mehrheits-HOLD) → Demo-Zahlen vor der Präsentation neu erheben; Antworten ohne Tool-Nutzung erscheinen
als schnelle Text-Bursts statt Token-Streaming (bewusst: schneller); die Mover-Discovery hängt an Yahoos
vordefinierten Screens (Fehler → ehrliche Fehler-JSON, kein Fallback-Raten).

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
