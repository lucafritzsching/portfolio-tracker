# 12. Data-Science-Methodik: Was die statistischen Modelle tun (und was nicht)

> Ehrliche, geprüfte Beschreibung der quantitativen Modelle hinter dem Statistik-Pfad des Agenten —
> **Daten, Features, Labels, Training, Libraries, Persistenz, Validierung und Grenzen**. Es ist ein
> Data-Science-Projekt: hier zählt methodische Sauberkeit + Ehrlichkeit, nicht „magische" Prognosen.
> Code: [`backend/agent/data_science.py`](../backend/agent/data_science.py).

## Überblick
| | **ARIMA** | **Random Forest** | **Ensemble** |
|---|---|---|---|
| Library | `statsmodels` | `scikit-learn` | eigener gewichteter Mix |
| Aufgabe | Kurs-Punktprognose 7/30 T | Klassifikation BUY/HOLD/SELL | eine reproduzierbare Entscheidung |
| Eingabe | Tages-Schlusskurse | 6 technische Features | alle Teilsignale |
| Persistenz | **keine** (refit pro Anfrage) | **keine** (refit pro Anfrage) | reine Funktion |
| Determinismus | ja (fit deterministisch) | ja (`random_state=42`) | ja (reine Funktion) |

Gemeinsame Datenquelle: `yfinance` (Tages-OHLCV, gecacht in `price_history`). **Kein Modell wird
gespeichert/versioniert** (kein `joblib`/`pickle`) — jede Anfrage trainiert frisch. Vorteil:
reproduzierbar + einfach; Nachteil: kein echtes „trainiertes, persistiertes" Modell (siehe Ausblick).

## ARIMA (`run_arima_forecast`)
- **Daten:** Schlusskurse, mind. 60 Punkte. **Ordnung fest `(2,1,2)`** für alle Titel — ein bewusster,
  einfacher Baseline-Wert, **keine** automatische Ordnungswahl (AIC-Grid/auto_arima). Folge: auf manchen
  Reihen konvergiert die MLE nicht sauber (ConvergenceWarning) — ehrlich dokumentiert, mit Fallback.
- **Prognose + Konfidenz:** `get_forecast(30)` liefert Mittelwert **und 95%-Prognoseintervall**. Die
  **Konfidenz** ist jetzt das Signal-Rausch-Verhältnis *vorhergesagte Bewegung / halbe Intervallbreite*
  (gekappt 0,05–0,95). **Wichtig (Fix):** die alte „Konfidenz" `1 − |AIC|/10000` war **statistisch
  sinnlos** (AIC ist kein Konfidenzmaß) und wurde ersetzt.
- **Baseline-Validierung (opt-in `validate=True`):** 30-Tage-Holdout — ARIMA wird auf allen Kursen bis
  auf die letzten 30 Tage gefittet, prognostiziert diese und berichtet den **MAE gegen die naive
  Random-Walk-Baseline** („Prognose = letzter Trainingskurs"). Aktiv im Statistik-Tool des Agenten und
  in `/agent/quick-stats`; im Backtest bewusst aus (dort fittet jedes Fenster ARIMA — die Validierung
  würde die Laufzeit ~verdoppeln). **Erwartbarer, ehrlicher Befund:** Auf Tagesschlusskursen schlägt
  ARIMA die Random-Walk-Baseline oft **nicht** — genau das wird berichtet, nicht versteckt.
- **Befund:** Die Intervalle sind breit (z. B. AAPL +30T-Prognose ≈ −0,2 %, Intervall ≈ [251, 340]) →
  **Konfidenz typischerweise niedrig (~5 %)**. Das ist die ehrliche Aussage: 30-Tage-Punktprognosen auf
  Einzelaktien sind hochgradig unsicher.

## Random Forest (`run_ml_signal`)
- **Library/Setup:** `RandomForestClassifier`, 100 Bäume, `random_state=42`, `StandardScaler`,
  **`class_weight="balanced"`** (die Labels sind HOLD-lastig — ohne Gewichtung lernt das Modell
  bevorzugt die Mehrheitsklasse).
- **Features (6, nur Vergangenheit):** RSI(14), MACD, 20-Tage-Volatilität, 10-Tage-Momentum,
  Kurs-vs-SMA20, Kurs-vs-SMA50.
- **Labels (aus der ZUKUNFT):** 20-Tage-Vorwärtsrendite > 3 % → BUY, < −3 % → SELL, sonst HOLD.
  (Korrekt: Labels müssen die Zukunft sein; Features nur die Vergangenheit — kein Look-ahead in den Features.)
- **Fixes:**
  1. **Vorhersage auf dem AKTUELLEN Bar.** Vorher entfernte `dropna()`+`X[-1:]` die letzten ~20 Zeilen →
     das „aktuelle" Signal war ~20 Tage alt. Jetzt: Training auf gelabelten Zeilen, **Vorhersage auf der
     letzten Feature-Zeile (heute)**.
  2. **Label-Fix:** Die letzten 20 Zeilen (Zukunftsrendite noch unbekannt, `NaN`) bekamen still das
     Default-Label HOLD und wurden **falsch gelabelt mittrainiert und mit-evaluiert** — jetzt vom
     Training ausgeschlossen (bleiben aber Feature-Zeilen für die aktuelle Vorhersage).
  3. **Purged Holdout + Mehrheits-Baseline:** zeitgeordneter Holdout (letzte 20 %) mit **20-Tage-Gap**
     (= Label-Horizont) zwischen Training und Test — sonst überlappen die Vorwärtslabels der letzten
     Trainingszeilen ins Testfenster (Leakage). Die Holdout-Genauigkeit wird **gegen die
     Mehrheitsklassen-Baseline** berichtet (Bewertungsmaßstab: schlägt das Modell stures
     „immer HOLD raten"?).
  4. **Robuste Wahrscheinlichkeiten** über `clf.classes_` (vorher IndexError möglich, wenn eine Klasse fehlte).
- **Befund:** Holdout-Genauigkeit z. B. **AAPL ≈ 51 %** (3 Klassen, HOLD-lastig) → **kaum besser als
  Raten**; der direkte Baseline-Vergleich steht jetzt in jedem `details`-Output. Ehrliche Aussage:
  das Modell hat auf diesen Daten **wenig prädiktive Kraft**.
- **Vorbehalt:** 20-Tage-Vorwärts-Labels auf Tagesdaten überlappen stark (autokorreliert) — die iid-Annahme
  des RF ist nur näherungsweise erfüllt; der purged Gap entschärft die Train/Test-Leakage, nicht die
  Überlappung innerhalb des Trainings.

## Ensemble (`compute_ensemble`)
Gewichteter Mix → Score (−1..+1) → BUY (>0,25) / HOLD / SELL (<−0,25):
Technik 0,30 · ARIMA 0,20 · Random Forest 0,25 · Fundamentals 0,10 · News 0,15. Reine Funktion (gleiche
Eingaben → gleiche Entscheidung).

## Validierung (Walk-Forward, `eval/backtest.py`)
Rollende Fenster, Vorwärtsrendite je Signal. Der Backtest berichtet jetzt zusätzlich eine
**`baseline`-Zeile: die Forward-Rendite ALLER Fenster unabhängig vom Signal (= Buy&Hold-Basisrate)**.
Das ist der Maßstab, den der Professor als „meaningful baseline" verlangt: ein BUY-Signal ist nur dann
gut, wenn seine ⌀-Rendite die Basisrate schlägt — nicht, wenn es in einem steigenden Markt einfach
positiv ist. Die Kernlogik ist als **pure Funktion `backtest_prices()`** extrahiert (ohne DB/IO
testbar, läuft via `asyncio.to_thread` außerhalb des Event-Loops) und als **Chat-Tool `run_backtest`**
in den Agenten eingebunden.

Zahlen vor den Fixes (AAPL+MSFT, Horizont 20 T, Schritt 10 T — **nach den Modell-Fixes neu erheben**):

| Signal | n | ⌀ Vorwärtsrendite | Trefferquote |
|---|---|---|---|
| BUY | 24 | −0,18 % | 54 % |
| HOLD | 35 | +0,35 % | 46 % |
| SELL | 13 | **+4,57 %** | 31 % |

**Ehrliche Interpretation:** Auf dieser (kleinen, n niedrig, **nicht signifikanten**) Stichprobe zeigt das
Ensemble **keinen verlässlichen Vorhersage-Vorteil** — SELL-Signale wurden im Schnitt sogar von *Kursanstiegen*
gefolgt. Das ist kein Bug, sondern der erwartbare Befund: Einzelaktien-Kurzfristprognose ist schwer.
**Der Wert des Projekts liegt im disziplinierten, nachvollziehbaren, ehrlichen Prozess** — deterministische
Berechnung als Rückgrat, das LLM eingehegt — nicht in einer Überrendite.

## Grenzen & Ausblick
- **Grenzen:** feste ARIMA-Ordnung; kein persistiertes/versioniertes Modell; kleine Validierungs-Stichprobe;
  überlappende RF-Labels innerhalb des Trainings (der purged Gap schützt nur Train/Test);
  Konfidenz ≠ Genauigkeit (RF-Konfidenz = Klassenwahrscheinlichkeit).
- **Umgesetzt (ADR-18):** Baseline-Vergleiche für alle drei Ebenen — RF vs. Mehrheitsklasse,
  ARIMA vs. Random Walk, Backtest vs. Buy&Hold — plus purged Split, `class_weight="balanced"`
  und der RF-Label-Fix.
- **Ausblick (dokumentiert, nicht umgesetzt):** `auto_arima`-Ordnungswahl; RF mit `TimeSeriesSplit`-CV +
  persistiertem, versioniertem Modell (`joblib`); größeres Backtest-Universum für Signifikanz;
  Feature-Erweiterung. Siehe [ADR-17](07-entscheidungslog.md)/[ADR-18](07-entscheidungslog.md).
