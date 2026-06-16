<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { api } from '@/api/client'
import { useMarkdown } from '@/composables/useMarkdown'
import type { AgentStatus } from '@/types'

// THE single agent window. One free-text question → the backend routing agent picks the right tool
// (strategy screen / NL-news judgment / statistics) and streams a visible tool-trace + explanation.
const portfolio = usePortfolioStore()
const md = useMarkdown()

const question = ref('')
const answer = ref('')
const running = ref(false)
const history = ref<{ q: string; a: string }[]>([])
const lastQuestion = ref('')

// ── Setup / Agent status (moved here from the old analysis view) ──────────────
const agentStatus = ref<AgentStatus | null>(null)
const statusLoading = ref(false)
const warming = ref(false)
const warmMsg = ref('')
const pulling = ref(false)
const pullLog = ref('')

onMounted(checkStatus)

async function checkStatus() {
  statusLoading.value = true
  try { agentStatus.value = await api.agent.status() } finally { statusLoading.value = false }
}

async function warmup() {
  warming.value = true
  warmMsg.value = ''
  try {
    const res = await api.marketData.warmup()
    warmMsg.value = `✓ Daten für ${res.warmed_up} Ticker vorbereitet.`
  } catch (e: any) {
    warmMsg.value = 'Fehler: ' + e.message
  } finally {
    warming.value = false
  }
}

async function pullModel() {
  pulling.value = true
  pullLog.value = 'Modell wird geladen…\n'
  const resp = await api.agent.pullModel()
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    for (const line of decoder.decode(value).split('\n').filter(l => l.startsWith('data: '))) {
      const data = line.replace('data: ', '')
      if (data === '[DONE]') { pulling.value = false; await checkStatus(); return }
      try {
        const p = JSON.parse(data)
        if (p.status) pullLog.value += p.status + (p.total ? ` (${p.completed ?? 0}/${p.total})` : '') + '\n'
      } catch { /* ignore */ }
    }
  }
  pulling.value = false
  await checkStatus()
}

// ── Chat ──────────────────────────────────────────────────────────────────────
// Conversation memory: send the last few turns so follow-ups ("prüf News für CRNX") can refer back.
// The tool-trace lines (> 🔧 …) are stripped to keep the context compact.
function buildHistory(): { role: string; content: string }[] {
  const msgs: { role: string; content: string }[] = []
  for (const t of history.value.slice(0, 3).reverse()) {
    msgs.push({ role: 'user', content: t.q.slice(0, 600) })
    const a = t.a.split('\n').filter((l) => !l.trim().startsWith('> 🔧')).join('\n').slice(0, 1200)
    if (a.trim()) msgs.push({ role: 'assistant', content: a })
  }
  return msgs
}

// Export exactly what the agent did (question + full answer incl. visible 🔧 tool-trace) as a .txt.
function exportLog() {
  const q = lastQuestion.value || history.value[0]?.q || ''
  const a = answer.value || history.value[0]?.a || ''
  if (!a) return
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  const text =
    `PortfAIo — KI-Agent Log\nZeit: ${new Date().toLocaleString('de-DE')}\n\n` +
    `Frage:\n${q}\n\nAntwort (inkl. sichtbarer Tool-Trace):\n${a}\n`
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `agent-log-${ts}.txt`
  link.click()
  URL.revokeObjectURL(url)
}

function ask() {
  const q = question.value.trim()
  if (!q || running.value) return
  running.value = true
  answer.value = ''
  lastQuestion.value = q
  const source = api.agent.ask(q, portfolio.currentPrices, buildHistory())
  source.onmessage = (e) => {
    if (e.data === '[DONE]') {
      running.value = false
      source.close()
      if (answer.value) history.value.unshift({ q, a: answer.value })
      question.value = ''
      return
    }
    answer.value += e.data.replace(/\\n/g, '\n')
  }
  source.onerror = () => {
    running.value = false
    source.close()
    if (!answer.value) answer.value = '[Verbindungsfehler zum Agenten]'
  }
}
</script>

<template>
  <div>
    <h2 class="section-title">KI-Agent</h2>

    <!-- Agent status / setup -->
    <div v-if="agentStatus" class="card" style="margin-bottom: 16px">
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px">
        <div style="font-size: 13px">
          <strong>Ollama-Agent</strong>
          <span v-if="agentStatus.ollama_reachable && agentStatus.model_available" class="badge badge-buy" style="margin-left: 8px">Bereit</span>
          <span v-else-if="agentStatus.ollama_reachable" class="badge badge-watch" style="margin-left: 8px">Modell fehlt</span>
          <span v-else class="badge badge-sell" style="margin-left: 8px">Nicht erreichbar</span>
          <span style="color: var(--text-secondary); margin-left: 8px">Modell: <strong>{{ agentStatus.model }}</strong></span>
        </div>
        <div style="display: flex; gap: 8px">
          <button class="btn btn-sm" @click="checkStatus" :disabled="statusLoading"><span v-if="statusLoading" class="spinner" /> ↻ Status</button>
          <button class="btn btn-sm" @click="warmup" :disabled="warming || portfolio.positions.length === 0" title="Kurse/Fundamentaldaten/News der Depot-Ticker vorab cachen">
            <span v-if="warming" class="spinner" /> ⬇ Daten vorbereiten
          </button>
          <button v-if="agentStatus.ollama_reachable && !agentStatus.model_available" class="btn btn-primary btn-sm" @click="pullModel" :disabled="pulling">
            <span v-if="pulling" class="spinner" /> Modell laden
          </button>
        </div>
      </div>
      <div v-if="warmMsg" style="margin-top: 8px; font-size: 12px; color: var(--text-secondary)">{{ warmMsg }}</div>
      <pre v-if="pullLog" style="margin-top: 10px; font-size: 11px; background: var(--bg-secondary); padding: 10px; border-radius: 6px; max-height: 120px; overflow-y: auto">{{ pullLog }}</pre>
    </div>

    <p style="color: var(--text-secondary); font-size: 13px; margin-bottom: 16px">
      Stell eine Freitext-Frage. Der Agent wählt selbst das passende Werkzeug und macht die Tool-Aufrufe
      sichtbar: <strong>Strategie-Screen</strong> (Unternehmen finden), <strong>News-/Klarsprache-Urteil</strong>
      (beleggebunden) oder <strong>statistische Modelle</strong> (ARIMA / Random Forest / Technik).
    </p>

    <div class="card" style="margin-bottom: 16px">
      <textarea
        v-model="question"
        rows="3"
        placeholder="z. B. 'Finde Nasdaq-Biotech unter 15 Mrd. mit Turnaround' · 'ARIMA-Signal für TSLA?' · 'Hat AAPL zuletzt gute News?'"
        style="width: 100%; padding: 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 14px; resize: vertical"
        :disabled="running"
        @keydown.ctrl.enter="ask"
      />
      <div style="margin-top: 10px; display: flex; justify-content: flex-end">
        <button class="btn btn-primary" :disabled="running || !question.trim()" @click="ask">
          <span v-if="running" class="spinner" />
          {{ running ? 'Agent arbeitet…' : 'Fragen' }}
        </button>
      </div>
    </div>

    <div v-if="answer && !running" style="display: flex; justify-content: flex-end; margin-bottom: 8px">
      <button class="btn btn-sm" @click="exportLog" title="Frage + Antwort + Tool-Trace als .txt speichern">⬇ Log exportieren</button>
    </div>
    <div v-if="answer" class="card ai-box markdown" v-html="md.render(answer)"></div>
    <div v-else-if="running" class="card ai-box" style="display: flex; align-items: center; gap: 10px; color: var(--text-tertiary)">
      <span class="spinner" /> Agent wählt Werkzeuge und sammelt Daten…
    </div>

    <div v-if="history.length > 1 || (history.length === 1 && !answer)" style="margin-top: 24px">
      <h3 class="section-title" style="font-size: 14px">Verlauf</h3>
      <div v-for="(h, i) in history.slice(answer ? 1 : 0)" :key="i" class="card" style="margin-bottom: 12px">
        <div style="font-weight: 600; font-size: 13px; margin-bottom: 8px">Frage: {{ h.q }}</div>
        <div class="markdown" v-html="md.render(h.a)"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.markdown { white-space: normal; }
.markdown :deep(h2) { font-size: 15px; font-weight: 800; margin: 12px 0 6px; }
.markdown :deep(h3) { font-size: 14px; font-weight: 800; margin: 12px 0 6px; }
.markdown :deep(p) { margin: 6px 0; }
.markdown :deep(ul) { margin: 6px 0; padding-left: 18px; }
.markdown :deep(strong) { font-weight: 700; }
/* visible tool-trace: the stream emits "> 🔧 Führe Tool aus: …" as blockquotes */
.markdown :deep(blockquote) {
  border-left: 3px solid var(--blue);
  background: var(--bg-secondary);
  margin: 8px 0;
  padding: 4px 12px;
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
