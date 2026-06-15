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
- **Befund:** Die Intervalle sind breit (z. B. AAPL +30T-Prognose ≈ −0,2 %, Intervall ≈ [251, 340]) →
  **Konfidenz typischerweise niedrig (~5 %)**. Das ist die ehrliche Aussage: 30-Tage-Punktprognosen auf
  Einzelaktien sind hochgradig unsicher.

## Random Forest (`run_ml_signal`)
- **Library/Setup:** `RandomForestClassifier`, 100 Bäume, `random_state=42`, `StandardScaler`.
- **Features (6, nur Vergangenheit):** RSI(14), MACD, 20-Tage-Volatilität, 10-Tage-Momentum,
  Kurs-vs-SMA20, Kurs-vs-SMA50.
- **Labels (aus der ZUKUNFT):** 20-Tage-Vorwärtsrendite > 3 % → BUY, < −3 % → SELL, sonst HOLD.
  (Korrekt: Labels müssen die Zukunft sein; Features nur die Vergangenheit — kein Look-ahead in den Features.)
- **Fixes:**
  1. **Vorhersage auf dem AKTUELLEN Bar.** Vorher entfernte `dropna()`+`X[-1:]` die letzten ~20 Zeilen →
     das „aktuelle" Signal war ~20 Tage alt. Jetzt: Training auf gelabelten Zeilen, **Vorhersage auf der
     letzten Feature-Zeile (heute)**.
  2. **Ehrliche Out-of-Sample-Genauigkeit:** zeitgeordneter Holdout (letzte 20 %).
  3. **Robuste Wahrscheinlichkeiten** über `clf.classes_` (vorher IndexError möglich, wenn eine Klasse fehlte).
- **Befund:** Holdout-Genauigkeit z. B. **AAPL ≈ 51 %** (3 Klassen, HOLD-lastig) → **kaum besser als
  Raten**. Ehrliche Aussage: das Modell hat auf diesen Daten **wenig prädiktive Kraft**.
- **Vorbehalt:** 20-Tage-Vorwärts-Labels auf Tagesdaten überlappen stark (autokorreliert) — die iid-Annahme
  des RF ist nur näherungsweise erfüllt.

## Ensemble (`compute_ensemble`)
Gewichteter Mix → Score (−1..+1) → BUY (>0,25) / HOLD / SELL (<−0,25):
Technik 0,30 · ARIMA 0,20 · Random Forest 0,25 · Fundamentals 0,10 · News 0,15. Reine Funktion (gleiche
Eingaben → gleiche Entscheidung).

## Validierung (Walk-Forward, `eval/backtest.py`)
Rollende Fenster, Vorwärtsrendite je Signal (AAPL+MSFT, Horizont 20 T, Schritt 10 T):

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
  überlappende RF-Labels; Konfidenz ≠ Genauigkeit (RF-Konfidenz = Klassenwahrscheinlichkeit).
- **Ausblick (dokumentiert, nicht umgesetzt):** `auto_arima`-Ordnungswahl; RF mit `TimeSeriesSplit`-CV +
  persistiertem, versioniertem Modell (`joblib`); größeres Backtest-Universum für Signifikanz;
  Feature-Erweiterung. Siehe [ADR-17](07-entscheidungslog.md).
