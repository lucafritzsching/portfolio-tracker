# Befund: `think:false` vs. `think:true` beim NL-Agenten (qwen3:14b)

**Frage:** Warum liefern Thinking-AUS und Thinking-AN unterschiedliche Ergebnisse — und welcher Modus ist
für unsere Aufgabe richtig? Reproduzierbar via [`think_mode_probe.py`](think_mode_probe.py) (gleicher
Produktions-Prompt `_format_prompt`, ein gebatchter Call, Temperatur 0, qwen3:14b lokal).

## Messung (2 Szenarien × 2 Modi)

| Szenario | Modus | Latenz | `thinking`-Feld | `<think>` im Body | Urteil (matches / strength) | Belege | Sprache |
|---|---|---|---|---|---|---|---|
| klar (Phase-3-Erfolg) | `think:false` | **16,8 s** | 0 | nein | True / 4 | [0,2] | Deutsch |
| klar (Phase-3-Erfolg) | `think:true`  | **66,4 s** | 3098 Zeichen | nein | True / 4 | [0,2] | Englisch |
| grenzwertig (schwach/mehrdeutig) | `think:false` | **9,0 s** | 0 | nein | True / 4 | [0,1,2,3] | Deutsch |
| grenzwertig (schwach/mehrdeutig) | `think:true`  | **90,0 s** | 4216 Zeichen | nein | True / 4 | [0,2,3] | Englisch |

## Was wirklich passiert (Mechanismus)
1. **Latenz ist der dominante, verlässliche Unterschied: 4–10×.** `think:true` erzeugt eine lange,
   verborgene Gedankenkette (≈3000–4200 Zeichen) **vor** der Antwort. Das ist exakt der per Eval
   diagnostizierte Defekt des alten fast-Pfads (≈41 s, weil Thinking implizit an war).
2. **Es ist KEIN Parsing-Problem.** Ollama liefert die Kette in einem **separaten `message.thinking`-Feld**;
   `content` bleibt in **beiden** Modi sauberes JSON (kein `<think>`-Leck). Die naheliegende Hypothese
   „Thinking zerschießt den JSON-Parser" trifft hier also **nicht** zu — das Urteil parst identisch.
3. **Das strukturierte Kern-Urteil ist robust:** `matches` und `strength` waren in **beiden** Fällen
   identisch (True / 4). Thinking kippt die Kern-Entscheidung hier also nicht.
4. **Wo es divergiert: in den Sekundär-Ausgaben.** Die **Beleg-Auswahl** ändert sich ([0,1,2,3] vs.
   [0,2,3]) und **Begründungstext + Sprache** (Deutsch bei `think:false`, Englisch bei `think:true` —
   qwen3 „denkt" auf Englisch, das färbt auf die Ausgabe ab). Das finale JSON ist auf die Kette
   konditioniert; bei **echt mehrdeutigen** Fällen kann diese Konditionierung auch strength/matches
   kippen (konsistent mit dem fast-vs-agentic-Genauigkeitsabstand der 36-Fälle-Eval), garantiert aber nicht.

## Konsequenz für Alt B
Für eine **eng begrenzte JSON-Klassifikation** (matches/strength/evidence) mit **Temperatur 0** und
**regex-Clamp** kostet die Gedankenkette 4–10× Latenz bei **praktisch keinem Gewinn** im strukturierten
Urteil — und bringt Sprach-/Beleg-Drift hinein. Deshalb ist **`think:false` der richtige Default**
(schneller, stabile Ausgabesprache, gleiche Entscheidung). Genau das war der Inhalt des Fixes `cc4e2e9`.

> **Für die Demo / Determinismus-vs-LLM-Achse:** Das ist ein sauberes, gemessenes Beispiel dafür, dass
> „mehr LLM-Nachdenken" ≠ „bessere Struktur-Ausgabe" — die deterministischen Leitplanken (Prompt-Constraint,
> T=0, Clamp) tragen das Ergebnis, nicht die Kette. Beleg, kein Bauchgefühl.

## Grenzen
n=2 Szenarien, je 1 Lauf/Modus (bei T=0 je Call deterministisch). Der Genauigkeits-Effekt auf wirklich
ambige Fälle ist hier nicht isoliert quantifiziert — dafür dient die 36-Fälle-Harness (separat).
