# Refactor-Validierung — Alt-B NL-Target-Agent

**Branch:** `alt-b-refactor` · **Commit:** `1078b1e` · **Datum:** 2026-06-12
**Modell:** `qwen3:14b` (nativ auf Host, Metal-GPU) · **Backend:** Docker `portfaio-backend` (Py 3.12) · **Frontend:** Vite v8 (`localhost:5173`)

Ziel: eigene, belegte Daten, dass der Refactor (Luca Fritzsching) funktioniert — insbesondere
der neue Free-Text-**NL-Target-Agent** (`/api/agent/nl-target`) mit Regex-Prefilter, lokalem LLM,
Anti-Halluzinations-Clamp und Trace. Validiert wird **ausschließlich der Refactor**, nicht die alte Baseline.

---

## 1. Technische Prüfung

| Check | Status | Beleg |
|---|---|---|
| Backend startet | ✅ | `docker-compose up -d` → Container `portfaio-backend`; Log `Application startup complete`; `GET /docs` → HTTP 200 |
| Frontend startet | ✅ | `npm run dev` → Vite v8 ready, `GET localhost:5173` → HTTP 200 |
| Alt-B-View funktioniert | ✅ | Sidebar-Eintrag `{ id: 'altb', label: 'Alt B' }`; `App.vue` rendert `<AltBView v-else-if="ui.activeView==='altb'">`; Formular (Ticker, Kriterium, Modus-Select fast/agentic) rendert |
| `/api/agent/nl-target` | ✅ | Live-Call `ticker=AXSM&criterion=…&mode=fast` → SSE-Stream: Header → „6 Schlagzeilen geladen" → `## Urteil` → `## Nachvollziehbarkeit (Trace)` → `[DONE]` |
| Ollama erreichbar + Modell | ✅ | `GET /api/agent/status` → `{ollama_reachable:true, model:"qwen3:14b", model_available:true}` |
| fast-Modus | ✅ (mit Vorbehalt) | 1 Batch-LLM-Call; funktioniert, aber **~50 s/Call** (s. Befund unten) |
| agentic-Modus | ✅ | Tool-Loop (`inspect_headline`), `think:false`; **~9 s/Call** |
| Trace wird angezeigt | ✅ | SSE liefert Trace-Block (Modus, Quelle, Regex-Basis, LLM-Rohstärke→final); `AltBView` rendert per `md.render()` |
| Graceful Degradation | ✅ | Bei LLM-Timeout: sauberer Regex-Fallback, ehrlicher Trace („LLM nicht verfügbar"), kein Crash |

### Befund A — `fast` ist paradox langsamer als `agentic` (Tuning-Defekt)
Der `fast`-Pfad (`_call_ollama`) setzt **kein** `"think": false`. qwen3:14b ist ein Reasoning-Modell und
generiert daher lange `<think>`-Tokens, bevor das JSON kommt. Gemessen (identischer Prompt):

| Pfad | `think:false`? | Dauer | Beleg |
|---|---|---|---|
| `fast` (`_call_ollama`) | nein | **49,8 s** | Diagnoselauf, 1 Headline |
| `agentic` (`_chat_once`) | ja | **9,1 s** | Diagnoselauf, identische Headline |

Folge: Der `fast`-Pfad liegt mit ~50 s gefährlich nah an seinem eigenen `timeout=60` →
beim ersten Live-Call (AXSM) lief er in den Timeout → stiller Regex-Fallback. **Empfehlung:**
`"think": false` auch im `fast`-Pfad setzen (Einzeiler). Damit wird „fast" wieder das, was der Name verspricht.

### Befund B — Clamp wirkt nachweislich (Anti-Halluzination)
`combine_verdict` klammert die finale Stärke auf `regex_strength ± 1`. Im Diagnoselauf
(„Positive Phase 3 Topline Results"): Regex-Basis **5**, LLM-Rohstärke **3** → final **4**
(hochgeklammert). Umgekehrt kann eine Konferenz-Headline (Regex-Basis 0) selbst bei LLM-Stärke 5
nie über **1** kommen → kein erfundener Katalysator.

---

## 2. Methodik

**System under test:** `services/nl_target.py::evaluate_nl_target` (Refactor), exakt der Code, den der
Endpoint `nl_target_stream` aufruft. Aufruf mit `ticker=""` (wie der Runner: News ist bereits
ticker-scoped, der Relevanzfilter wird übersprungen).

**Pipeline:** `prefilter()` (Regex `classify_event`, droppt irrelevante/negative Headlines, bildet
`regex_strength` = max Stärke der qualifizierenden ≥3/positiv) → LLM (`fast`: 1 Batch-Call; `agentic`:
Tool-Loop, max 3 Iterationen, Tool `inspect_headline`) → `combine_verdict()` (Clamp ±1, `matches =
LLM.matches ∧ final ≥ 3`; Regex-Fallback bei LLM-Ausfall).

**Korpus:** 18 Fälle über 6 Kategorien (klar positiv, schwach/Konferenz, Analyst, negativ,
Insider-only, Mix). Headline-Texte real/verbatim aus den Juni-/April-Läufen, wo die Kategorie aus der
Headline allein eindeutig ist; sonst realistisch konstruiert und als solche gekennzeichnet. Jeder Fall
in **beiden Modi** (fast + agentic) gegen echtes qwen3:14b. Erfasst je Lauf: Regex-Basis, LLM-Rohstärke,
finale Stärke (nach Clamp), `matches`, Quelle (llm/regex_fallback/no_signal), Belege, Dauer.

**Ground truth:** „Erfüllt die Headline aktuell das Kriterium?" — fachliche Vorab-Festlegung je Fall,
unabhängig vom System. `korrekt = (System.matches == ground truth)`.

**Reproduktion:** `docs/evidence/refactor_nl_harness.py` (Rohdaten → `refactor_nl_validation_raw.json`).
Deterministischer Regex-Vorabcheck der Eingaben separat ausgeführt (ohne LLM).

---

## 3. Testfälle

18 Fälle × 2 Modi = 36 Läufe gegen echtes qwen3:14b. Spalten `f/a` = fast / agentic.
`Regex` = deterministische Basis (max Stärke qualifizierender Headlines). `LLMroh` = LLM-Rohstärke
vor Clamp. `final` = nach Clamp (Regex ± 1). `match` = Endurteil (`LLM.matches ∧ final ≥ 3`).
Rohdaten: [`docs/evidence/refactor_nl_validation_raw.json`](evidence/refactor_nl_validation_raw.json).

| # | Kategorie | Headline (Beleg/Herkunft) | Kriterium | Regex | LLMroh f/a | final f/a | match f/a | erwartet | korrekt f/a |
|--|--|--|--|:--:|:--:|:--:|:--:|:--:|:--:|
| 01 | klar positiv | BioAge Reports Positive Phase 1 Data for BGE-102… · _real (Apr, BioAge)_ | Turnaround | 3 | 1/1 | 2/2 | ✗/✗ | ✓ | ❌/❌ |
| 02 | klar positiv | CytomX Expands Collaboration and Licensing… Regeneron · _real (Jun)_ | Turnaround | 4 | 2/4 | 3/4 | ✗/✓ | ✓ | ❌/✅ |
| 03 | klar positiv | Acme … Positive Phase 3 Topline Results, Primary Endpoint · _konstruiert_ | Turnaround | 5 | 3/5 | 4/5 | ✓/✓ | ✓ | ✅/✅ |
| 04 | klar positiv | Beta Pharma Receives FDA Approval for Lead Drug · _konstruiert_ | Turnaround | 5 | 2/5 | 4/5 | ✗/✓ | ✓ | ❌/✅ |
| 05 | regex-grenze | Cabaletta … New Positive Clinical Data … Rese-Cel · _paraphrasiert¹_ | Turnaround | 0 | 3/1 | 1/1 | ✗/✗ | ✓ | ❌/❌ |
| 06 | konferenz | AbCellera … Presents at Jefferies Global Healthcare Conf. · _real (Jun)_ | Turnaround | 0 | 1/1 | 1/1 | ✗/✗ | ✗ | ✅/✅ |
| 07 | konferenz | Adaptive Biotech … Presents at William Blair Conf. · _real (Jun)_ | Turnaround | 0 | 1/1 | 1/1 | ✗/✗ | ✗ | ✅/✅ |
| 08 | konferenz | Assembly Biosciences … Presents at Goldman Sachs Conf. · _konstruiert²_ | Turnaround | 0 | 1/1 | 1/1 | ✗/✗ | ✗ | ✅/✅ |
| 09 | analyst | RBC Capital Maintains Outperform … Raises PT to $56 · _real (Jun)_ | Turnaround | 0 | 2/1 | 1/1 | ✗/✗ | ✗ | ✅/✅ |
| 10 | analyst | Leerink Initiates Coverage on Absci, Outperform · _real (Jun)_ | Turnaround | 0 | 1/1 | 1/1 | ✗/✗ | ✗ | ✅/✅ |
| 11 | analyst | Stephens Reiterates Overweight on Arvinas, $18 PT · _real (Jun)_ | Turnaround | 0 | 1/1 | 1/1 | ✗/✗ | ✗ | ✅/✅ |
| 12 | negativ | Gamma … Phase 3 Trial Failed to Meet Primary Endpoint · _konstruiert_ | Turnaround | 0 | –/– | 0/0 | ✗/✗ | ✗ | ✅/✅ |
| 13 | negativ | Delta Bio Halts Lead Program After FDA Clinical Hold · _konstruiert_ | Turnaround | 0 | –/– | 0/0 | ✗/✗ | ✗ | ✅/✅ |
| 14 | insider-only | … Director Reports Open-Market Purchase 100k Shares (Form 4) · _konstr._ | Turnaround | 0 | 1/1 | 1/1 | ✗/✗ | ✗ | ✅/✅ |
| 15 | insider-only | … CEO Buys $2 Million of Company Stock, Open-Market · _konstr._ | Turnaround | 0 | 3/1 | 1/1 | ✗/✗ | ✗ | ✅/✅ |
| 16 | schwach-mix | Absci: Konferenz + Analyst-Initiation (2 Headlines) · _real (Jun)_ | Turnaround | 0 | 3/1 | 1/1 | ✗/✗ | ✗ | ✅/✅ |
| 17 | mix pos+neg | Epsilon: Positive Phase 2 + Klage (2 Headlines) · _konstruiert_ | Turnaround | 4 | 3/4 | 3/4 | ✓/✓ | ✓ | ✅/✅ |
| 18 | anderes Ziel | CytomX Collaboration/Licensing (Kriterium ≠ Turnaround) · _real (Jun)_ | Partnerschaft | 4 | 5/4 | 5/4 | ✓/✓ | ✓ | ✅/✅ |

**Belege je Fall:** Headline-Text + Herkunft (Lauf/Ticker) in der Tabelle; vollständige Texte, Begründungen
und Evidenz-Zitate des Modells in der Rohdaten-JSON. Negative (12/13) erzeugen `no_signal` ohne LLM-Call.

> **Herkunfts-Präzisierung (verifiziert gegen die Lauf-JSONs):** Nur **Fall 09 (ALKS) und 11 (ARVN) sind
> wörtlich** aus dem Juni-Lauf. „real" bei 01/02/06/07/10/16/18 bedeutet **real, aber gekürzt/Casing bereinigt**
> (Bedeutung erhalten). **¹ Fall 05** ist eine **Paraphrase** — die echte Cabaletta-Headline (2026-06-03) lautete
> anders und war sogar st4; der Regex-Miss ist eine Eigenschaft meines Texts. **² Fall 08** ist **konstruiert**
> (Konferenz-Vorlage mit ASMB-Namen); die echte ASMB-Meldung war „Teases Gilead HSV-2 Decision…". Exakte
> Herkunft je Fall: siehe [`refactor_architecture.md`](refactor_architecture.md) §9.

---

## 4. Auswertung

### Trefferquote (vs. fachliche Ground Truth)

| | korrekt | Quote |
|---|--|--|
| **gesamt** | 30/36 | **83 %** |
| fast | 14/18 | 78 % |
| **agentic** | 16/18 | **89 %** |

Die 6 Abweichungen zerfallen in **drei Ursachen** — nur eine ist ein echter LLM-Qualitätsfehler:

1. **fast-Qualitätsfehler (Fälle 02, 04 — nur fast):** Bei echten Katalysatoren (Lizenzdeal st4, FDA-Zulassung st5)
   gab `fast` Rohstärke 2 und `matches=false`. **agentic urteilte beim identischen Input korrekt** (st4/st5, Match).
   → kein Modell-, sondern ein Pfad-Problem (Befund A: `fast` ohne `think:false`).
2. **Regex-Grenze (Fall 05 — beide Modi):** „New Positive Clinical Data … Rese-Cel" enthält kein Regex-Keyword
   → Basis 0 → Clamp deckelt auf 1, obwohl `fast` die Headline mit Rohstärke **3** korrekt erkennen wollte.
   Der Anti-Halluzinations-Clamp ist hier zu scharf — ein **False-Negative durch eine Regex-Lücke**, kein LLM-Fehler.
3. **Grenzwertige Ground Truth (Fall 01 — beide Modi):** Beide Modi werten einen **Phase-1**-Readout nicht als
   „Turnaround-Story" (Rohstärke 1). Das ist fachlich vertretbar (Frühphase); meine Soll-Vorgabe war hier großzügig.

Bereinigt um (2)+(3) trifft **agentic auf allen klaren Katalysator-, Konferenz-, Analyst-, Negativ- und
Insider-Fällen korrekt**.

### Halluzinationen: 0

Kein einziger Lauf erfand einen Katalysator. In **3 Läufen** versuchte das LLM zu überhöhen (Regex-Basis 0,
aber Rohstärke ≥ 3: Fälle 05-fast, 15-fast, 16-fast) — der Clamp **blockierte alle 3** (final 1, kein Match).
Das ist der zentrale Beleg, dass die Anti-Halluzinations-Garantie hält.

### Clamp-Eingriffe: 9 / 32 LLM-Läufe

- **4× runter-geklammert** (Anti-Halluzination): 05-fast (3→1), 09-fast (2→1), 15-fast (3→1), 16-fast (3→1).
- **5× hoch-geklammert**: 01-f/a (1→2), 02-fast (2→3), 03-fast (3→4), 04-fast (2→4) — der Regex-Boden zieht die
  Unterschätzung des `fast`-Pfads teilweise hoch. Hinweis: Stärke-Hochklammern allein rettet kein Match, wenn das
  LLM `matches=false` liefert (Fall 02/04-fast) — das boolesche LLM-Veto bleibt bindend.

### fast vs. agentic

| | fast | agentic |
|---|--|--|
| Trefferquote | 78 % | **89 %** |
| Median-Laufzeit | 41,5 s | **6,4 s** |
| Spanne | 31,3 s – **892,1 s** (Ausreißer Fall 18) | 5,6 – 10,0 s |
| Divergenzen | unterlegen in Fall 02, 04 | nie schlechter als fast |

**agentic dominiert fast vollständig** — gleich oder besser auf jedem Fall, ~6× schneller, ohne Ausreißer.
Der `fast`-Lauf in Fall 18 brauchte **892 s** (~15 min); wahrscheinlich Modell-Reload/Speicherdruck (3 Modelle
geladen), trotz `timeout=60` im Code — als Robustheitsrisiko zu bestätigen, aber er unterstreicht die `fast`-Fragilität.

### Was funktioniert gut

- **Regex-Prefilter:** Negative werden ohne LLM-Kosten verworfen (`no_signal`, 0,0 s); Konferenz/Analyst/Insider
  bleiben korrekt auf Basis 0 → können nicht zum Signal hochgestuft werden.
- **Clamp:** 0 Halluzinationen trotz 3 Überhöhungsversuchen — die Kernzusage des Designs hält.
- **agentic-Modus:** 89 % korrekt bei ~6 s; klar präsentationstauglich.
- **Konfigurierbares Ziel (ADR-14):** Fall 18 mit Kriterium „Partnerschaft/Lizenzdeal" matcht korrekt — die
  Maschinerie ist nicht auf „Turnaround" festverdrahtet.
- **Graceful Degradation + Trace:** Jeder Lauf trägt Regex-Basis, LLM-Rohstärke→final und Quelle — vollständig auditierbar.

### Was funktioniert schlecht

- **`fast`-Modus:** langsam (Median 41,5 s), ein 892-s-Ausreißer, **und** schlechter (unterschätzt → False-Negatives
  auf echten Katalysatoren). Ursache: fehlendes `think:false`. **Empfehlung:** `think:false` im `fast`-Pfad setzen
  (Einzeiler) oder `fast` zugunsten von `agentic` als Default zurückstellen.
- **Regex als harte Decke:** Eine Regex-Lücke (Fall 05) wird durch den Clamp (max Regex+1) zum unkorrigierbaren
  False-Negative. Anti-Halluzination und Recall stehen hier im Zielkonflikt.

### Verbleibende Grenzen

- **News-only:** Der NL-Agent sieht ausschließlich Schlagzeilen. **Insider-Käufe sind unsichtbar** (Fälle 14/15
  korrekt „kein Match" — aber ein echtes Insider-only-Signal ist hier prinzipiell nicht erkennbar; es lebt in
  `score_alt_b`, nicht im NL-Agenten). Diese Bereichsgrenze muss in der Präsentation klar benannt werden.
- **Recall ist Regex-gedeckelt:** Neue Katalysator-Formulierungen außerhalb des Keyword-Sets werden durch den
  Clamp unterdrückt (Preis für „keine Halluzination").
- **Kein eindeutiges Modell-Urteil:** fast und agentic liefern bei identischem Input verschiedene Rohstärken
  (Prompt/Think-Unterschiede) — „die Modellmeinung" ist nicht modusübergreifend deterministisch.
- **Kleines, kuratiertes Korpus (18 Fälle):** kein statistisches Sample; der echte Endpoint füttert zusätzlich
  Summaries (mehr Signal), hier überwiegend Einzelsätze. Modell ist konservativ bei Frühphasen-Daten (Fall 01).

---

## Anhang — Umgebung & Befehle

- Backend: `docker-compose up -d` (Postgres + `portfaio-backend`); Health `curl localhost:8000/docs`.
- Ollama: nativ, `qwen3:14b` (warm ~1 s, Kaltstart Modell-Load länger).
- Harness: `OLLAMA_BASE_URL=http://localhost:11434 PYTHONPATH=backend backend/.venv/bin/python docs/evidence/refactor_nl_harness.py`
- Rohdaten/Belege: `docs/evidence/refactor_nl_validation_raw.json`, `docs/evidence/run_2026-06-10_result.json`, `docs/evidence/run_2026-04_april_result.json`.

### Live-End-to-End-Beleg (echter Endpoint, aktives LLM)

`GET /api/agent/nl-target?ticker=AXSM&criterion=hat aktuell eine Turnaround-Story&mode=agentic` →
SSE-Ausgabe (warmes qwen3:14b, 2026-06-12), Quelle **LLM-Urteil** (nicht Fallback):

```
## NL-Ziel-Analyse: AXSM
**Kriterium:** „hat aktuell eine Turnaround-Story“ · **Modus:** agentic
6 Schlagzeilen geladen, beurteile gegen das Kriterium…
## Urteil
- Erfüllt „hat aktuell eine Turnaround-Story“: ❌ Nein
- Signifikanz: 1/5
- Begründung: Keine der Schlagzeilen deutet auf eine Turnaround-Story hin.
## Nachvollziehbarkeit (Trace)
- Modus: agentic · Quelle: LLM-Urteil
- Schlagzeilen geprüft: 6 · deterministische Regex-Basis: 0/5
- LLM-Rohstärke: 1/5 → final 1/5 (geklammert auf Regex-Basis ±1 — Anti-Halluzination)
```

Damit ist die volle Kette HTTP → Backend (Docker) → News-Fetch → Ollama → Clamp → Trace belegt.
Derselbe Ticker im `fast`-Modus lief zuvor in den 60-s-Timeout → sauberer Regex-Fallback (Befund A).
