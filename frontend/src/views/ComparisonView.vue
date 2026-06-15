<script setup lang="ts">
import { ref, type Ref } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { api } from '@/api/client'
import { useMarkdown } from '@/composables/useMarkdown'

// Side-by-side comparison of the two alternatives on ONE shared input, reusing the EXISTING
// endpoints (no backend change, Alt A untouched). Left = Alt A (deterministic ensemble decides,
// LLM only explains, evidence-gated). Right = Alt B (LLM judges a free-text criterion, regex-clamped).
const portfolio = usePortfolioStore()
const md = useMarkdown()

const ticker = ref('')
const criterion = ref('hat aktuell eine Turnaround-Story')

const aAgentic = ref(false)               // Alt A: 1 LLM-Call vs. sichtbarer Tool-Loop
const bMode = ref<'fast' | 'agentic'>('fast')  // Alt B: fast (1 Call) vs. agentic (Tool-Loop)

const aText = ref('')
const bText = ref('')
const aRunning = ref(false)
const bRunning = ref(false)

// Alt A streams the deterministic decision first, then "## Begründung des Agenten" — split so we can
// show "Code entscheidet" and "LLM erklärt" as two distinct blocks.
const AGENT_MARKER = '## Begründung des Agenten'
function splitA(text: string): { decision: string; agent: string } {
  const idx = text.indexOf(AGENT_MARKER)
  if (idx === -1) return { decision: text, agent: '' }
  return {
    decision: text.slice(0, idx).replace(/\n*---\n*$/, '').trim(),
    agent: text.slice(idx).trim(),
  }
}

function streamInto(source: EventSource, textRef: Ref<string>, runningRef: Ref<boolean>) {
  runningRef.value = true
  textRef.value = ''
  source.onmessage = (e) => {
    if (e.data === '[DONE]') { runningRef.value = false; source.close(); return }
    textRef.value += e.data.replace(/\\n/g, '\n')
  }
  source.onerror = () => {
    runningRef.value = false
    source.close()
    if (!textRef.value) textRef.value = '[Verbindungsfehler zum Agenten]'
  }
}

function runA() {
  const t = ticker.value.trim().toUpperCase()
  if (!t || aRunning.value) return
  streamInto(api.agent.analyzeStock(t, portfolio.currentPrices, aAgentic.value), aText, aRunning)
}
function runB() {
  const t = ticker.value.trim().toUpperCase()
  const c = criterion.value.trim()
  if (!t || !c || bRunning.value) return
  streamInto(api.agent.nlTarget(c, t, bMode.value), bText, bRunning)
}
function runBoth() { runA(); runB() }
</script>

<template>
  <div>
    <h2 class="section-title">Vergleich — Alt A vs. Alt B</h2>

    <!-- Explainer legend -->
    <div class="card legend" style="margin-bottom: 16px">
      <div class="legend-grid">
        <div>
          <span class="badge badge-blue">Alt A · deterministisch</span>
          <p>Der <strong>Code entscheidet</strong> (Ensemble: Technik/Bollinger + ARIMA + RandomForest +
          Fundamentals + News → BUY/HOLD/SELL). Das <strong>LLM erklärt nur</strong> — abgesichert durch
          ein <strong>Evidence-Gate</strong> (unbelegte Sätze werden entfernt).</p>
        </div>
        <div>
          <span class="badge badge-buy">Alt B · NL / LLM</span>
          <p>Das <strong>LLM beurteilt</strong> ein Freitext-Kriterium gegen aktuelle News — abgesichert
          durch einen <strong>Clamp</strong> (regex-Basis ±1): die Signifikanz kann nie über die
          deterministische Basis hinaus „erfunden" werden.</p>
        </div>
      </div>
      <p class="legend-note">
        <strong>Modus-Achse:</strong> „1 LLM-Call" (schnell, mit Trace) ↔ „Tool-Calling-Agent" (ruft sichtbar
        Tools auf). <em>Multi-Agent ist Ausblick, noch nicht gebaut.</em>
      </p>
    </div>

    <!-- Shared input -->
    <div class="card" style="margin-bottom: 16px">
      <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center">
        <input
          v-model="ticker"
          placeholder="Ticker, z. B. AAPL"
          :disabled="aRunning || bRunning"
          style="flex: 0 0 160px; padding: 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 14px"
          @keydown.enter="runBoth"
        />
        <input
          v-model="criterion"
          placeholder="NL-Kriterium (für Alt B)"
          :disabled="aRunning || bRunning"
          style="flex: 1 1 260px; padding: 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 14px"
          @keydown.enter="runBoth"
        />
        <button class="btn btn-primary" :disabled="!ticker.trim() || aRunning || bRunning" @click="runBoth">
          <span v-if="aRunning || bRunning" class="spinner" />
          {{ (aRunning || bRunning) ? 'Läuft…' : 'Beide starten' }}
        </button>
      </div>
    </div>

    <!-- Two columns -->
    <div class="cmp-grid">
      <!-- Alt A -->
      <div class="cmp-col">
        <div class="cmp-head">
          <span class="badge badge-blue">Alt A — deterministisch (DS)</span>
          <label class="toggle" title="Agent ruft sichtbar Tools auf (langsamer)">
            <input type="checkbox" v-model="aAgentic" :disabled="aRunning" /> Tool-Agent
          </label>
          <button class="btn btn-sm" :disabled="!ticker.trim() || aRunning" @click="runA">
            <span v-if="aRunning" class="spinner" /> Nur A
          </button>
        </div>
        <template v-if="aText">
          <div class="ai-box decision-box markdown" v-html="md.render(splitA(aText).decision)"></div>
          <div v-if="splitA(aText).agent" class="ai-box markdown" style="margin-top: 10px" v-html="md.render(splitA(aText).agent)"></div>
        </template>
        <div v-else-if="aRunning" class="ai-box muted"><span class="spinner" /> Ensemble rechnet, LLM begründet…</div>
        <p v-else class="muted-text">Code entscheidet, LLM erklärt (evidence-gated).</p>
      </div>

      <!-- Alt B -->
      <div class="cmp-col">
        <div class="cmp-head">
          <span class="badge badge-buy">Alt B — NL / LLM</span>
          <label class="toggle">
            Modus:
            <select v-model="bMode" :disabled="bRunning" style="padding: 5px; border-radius: 6px; border: 1px solid var(--border)">
              <option value="fast">fast</option>
              <option value="agentic">agentic</option>
            </select>
          </label>
          <button class="btn btn-sm" :disabled="!ticker.trim() || !criterion.trim() || bRunning" @click="runB">
            <span v-if="bRunning" class="spinner" /> Nur B
          </button>
        </div>
        <div v-if="bText" class="ai-box markdown" v-html="md.render(bText)"></div>
        <div v-else-if="bRunning" class="ai-box muted"><span class="spinner" /> LLM beurteilt das Kriterium…</div>
        <p v-else class="muted-text">LLM beurteilt das NL-Kriterium (regex-geklammert).</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.legend-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.legend p { margin: 6px 0 0; font-size: 13px; color: var(--text-secondary); }
.legend-note { margin: 12px 0 0; font-size: 12.5px; color: var(--text-secondary); border-top: 1px solid var(--border); padding-top: 10px; }

.cmp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
.cmp-col { min-width: 0; }
.cmp-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.toggle { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); cursor: pointer; }

.muted { display: flex; align-items: center; gap: 10px; color: var(--text-tertiary); }
.muted-text { color: var(--text-tertiary); font-size: 13px; }
.decision-box { border-left: 3px solid var(--blue); }

.markdown { white-space: normal; }
.markdown :deep(h2) { font-size: 15px; font-weight: 800; margin: 12px 0 6px; }
.markdown :deep(h3) { font-size: 14px; font-weight: 800; margin: 12px 0 6px; }
.markdown :deep(p) { margin: 6px 0; }
.markdown :deep(ul) { margin: 6px 0; padding-left: 18px; }
.markdown :deep(strong) { font-weight: 700; }

@media (max-width: 860px) {
  .legend-grid, .cmp-grid { grid-template-columns: 1fr; }
}
</style>
