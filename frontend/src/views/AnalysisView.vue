<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { api } from '@/api/client'
import { useFormatters } from '@/composables/useFormatters'
import { useMarkdown } from '@/composables/useMarkdown'
import type { AgentStatus } from '@/types'

const portfolio = usePortfolioStore()
const { fmt, fmtPct } = useFormatters()
const md = useMarkdown()

const agentStatus = ref<AgentStatus | null>(null)
const statusLoading = ref(false)
const analysisText = ref<Record<string, string>>({})
const analysisRunning = ref<Record<string, boolean>>({})
const portfolioAnalysis = ref('')
const portfolioAnalysisRunning = ref(false)
const pullingModel = ref(false)
const pullLog = ref('')
const agenticMode = ref(false)
const newsSummary = ref<Record<string, string>>({})
const newsSummaryRunning = ref<Record<string, boolean>>({})
const rebalanceText = ref('')
const rebalanceRunning = ref(false)

onMounted(checkAgentStatus)

async function checkAgentStatus() {
  statusLoading.value = true
  try {
    agentStatus.value = await api.agent.status()
  } finally {
    statusLoading.value = false
  }
}

async function pullModel() {
  pullingModel.value = true
  pullLog.value = 'Modell wird heruntergeladen...\n'
  const resp = await api.agent.pullModel()
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const text = decoder.decode(value)
    const lines = text.split('\n').filter(l => l.startsWith('data: '))
    for (const line of lines) {
      const data = line.replace('data: ', '')
      if (data === '[DONE]') { pullingModel.value = false; await checkAgentStatus(); return }
      try {
        const parsed = JSON.parse(data)
        if (parsed.status) pullLog.value += parsed.status + (parsed.total ? ` (${parsed.completed ?? 0}/${parsed.total})` : '') + '\n'
      } catch { /* ignore */ }
    }
  }
  pullingModel.value = false
  await checkAgentStatus()
}

function analyzeStock(ticker: string) {
  if (analysisRunning.value[ticker]) return
  analysisRunning.value[ticker] = true
  analysisText.value[ticker] = ''

  const source = api.agent.analyzeStock(ticker, portfolio.currentPrices, agenticMode.value)
  source.onmessage = (e) => {
    if (e.data === '[DONE]') {
      analysisRunning.value[ticker] = false
      source.close()
      return
    }
    // Unescape \n back to newlines
    analysisText.value[ticker] = (analysisText.value[ticker] || '') + e.data.replace(/\\n/g, '\n')
  }
  source.onerror = () => {
    analysisRunning.value[ticker] = false
    source.close()
    if (!analysisText.value[ticker]) analysisText.value[ticker] = '[Verbindungsfehler zum Agenten]'
  }
}

function summarizeNews(ticker: string) {
  if (newsSummaryRunning.value[ticker]) return
  newsSummaryRunning.value[ticker] = true
  newsSummary.value[ticker] = ''
  const source = api.agent.newsSummary(ticker)
  source.onmessage = (e) => {
    if (e.data === '[DONE]') { newsSummaryRunning.value[ticker] = false; source.close(); return }
    newsSummary.value[ticker] = (newsSummary.value[ticker] || '') + e.data.replace(/\\n/g, '\n')
  }
  source.onerror = () => {
    newsSummaryRunning.value[ticker] = false
    source.close()
    if (!newsSummary.value[ticker]) newsSummary.value[ticker] = '[Verbindungsfehler zum Agenten]'
  }
}

function runRebalance() {
  if (rebalanceRunning.value) return
  rebalanceRunning.value = true
  rebalanceText.value = ''
  const source = api.agent.rebalance(portfolio.currentPrices)
  source.onmessage = (e) => {
    if (e.data === '[DONE]') { rebalanceRunning.value = false; source.close(); return }
    rebalanceText.value += e.data.replace(/\\n/g, '\n')
  }
  source.onerror = () => {
    rebalanceRunning.value = false
    source.close()
    if (!rebalanceText.value) rebalanceText.value = '[Verbindungsfehler zum Agenten]'
  }
}

function analyzePortfolio() {
  if (portfolioAnalysisRunning.value) return
  portfolioAnalysisRunning.value = true
  portfolioAnalysis.value = ''

  const source = api.agent.analyzePortfolio(portfolio.currentPrices)
  source.onmessage = (e) => {
    if (e.data === '[DONE]') {
      portfolioAnalysisRunning.value = false
      source.close()
      return
    }
    portfolioAnalysis.value += e.data.replace(/\\n/g, '\n')
  }
  source.onerror = () => {
    portfolioAnalysisRunning.value = false
    source.close()
    if (!portfolioAnalysis.value) portfolioAnalysis.value = '[Verbindungsfehler zum Agenten]'
  }
}

const warmingUp = ref(false)
const warmupMsg = ref('')

async function warmup() {
  warmingUp.value = true
  warmupMsg.value = ''
  try {
    const res = await api.marketData.warmup()
    warmupMsg.value = `✓ Daten für ${res.warmed_up} Ticker vorbereitet.`
  } catch (e: any) {
    warmupMsg.value = 'Fehler: ' + e.message
  } finally {
    warmingUp.value = false
  }
}

// The stream sends the deterministic decision first, then "## Begründung des Agenten".
// Split so we can show them as two distinct cards.
const AGENT_MARKER = '## Begründung des Agenten'
function splitAnalysis(text: string): { decision: string; agent: string } {
  const idx = text.indexOf(AGENT_MARKER)
  if (idx === -1) return { decision: text, agent: '' }
  return {
    decision: text.slice(0, idx).replace(/\n*---\n*$/, '').trim(),
    agent: text.slice(idx).trim(),
  }
}
</script>

<template>
  <div>
    <!-- Agent Status Banner -->
    <div v-if="agentStatus" class="card" style="margin-bottom: 20px">
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px">
        <div>
          <div style="font-weight: 700; font-size: 15px; margin-bottom: 4px">
            Ollama-Agent
            <span v-if="agentStatus.ollama_reachable && agentStatus.model_available" class="badge badge-buy" style="margin-left: 8px">Bereit</span>
            <span v-else-if="agentStatus.ollama_reachable" class="badge badge-watch" style="margin-left: 8px">Modell fehlt</span>
            <span v-else class="badge badge-sell" style="margin-left: 8px">Nicht erreichbar</span>
          </div>
          <div style="color: var(--text-secondary); font-size: 13px">
            Modell: <strong>{{ agentStatus.model }}</strong>
            <span v-if="agentStatus.available_models?.length"> · Verfügbar: {{ agentStatus.available_models.join(', ') }}</span>
          </div>
          <div v-if="agentStatus.error" style="color: var(--red); font-size: 12px; margin-top: 2px">{{ agentStatus.error }}</div>
        </div>
        <div style="display: flex; gap: 8px">
          <button class="btn btn-sm" @click="checkAgentStatus" :disabled="statusLoading">
            <span v-if="statusLoading" class="spinner" /> <span v-else>↻ Status prüfen</span>
          </button>
          <button class="btn btn-sm" @click="warmup" :disabled="warmingUp || portfolio.positions.length === 0" title="Kurse, Fundamentaldaten und News für alle Positionen vorab cachen">
            <span v-if="warmingUp" class="spinner" /> <span v-else>⬇ Daten vorbereiten</span>
          </button>
          <button
            v-if="agentStatus.ollama_reachable && !agentStatus.model_available"
            class="btn btn-primary btn-sm"
            @click="pullModel"
            :disabled="pullingModel"
          >
            <span v-if="pullingModel" class="spinner" /> Modell laden
          </button>
        </div>
      </div>
      <div v-if="warmupMsg" style="margin-top: 8px; font-size: 12px; color: var(--text-secondary)">{{ warmupMsg }}</div>
      <pre v-if="pullLog" style="margin-top: 12px; font-size: 11px; background: var(--bg-secondary); padding: 10px; border-radius: 6px; max-height: 120px; overflow-y: auto">{{ pullLog }}</pre>
    </div>

    <!-- Portfolio Analysis -->
    <div class="card" style="margin-bottom: 20px">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px">
        <h2 class="section-title" style="margin: 0">Portfolio-Analyse</h2>
        <div style="display: flex; gap: 8px">
          <button
            class="btn btn-sm"
            @click="runRebalance"
            :disabled="rebalanceRunning || !agentStatus?.ollama_reachable || portfolio.positions.length === 0"
            title="KI-Vorschläge zur Diversifikation / Umschichtung"
          >
            <span v-if="rebalanceRunning" class="spinner" /> ⚖️ Rebalancing-Vorschläge
          </button>
          <button
            class="btn btn-primary"
            @click="analyzePortfolio"
            :disabled="portfolioAnalysisRunning || !agentStatus?.ollama_reachable"
          >
            <span v-if="portfolioAnalysisRunning" class="spinner" />
            {{ portfolioAnalysisRunning ? 'Analysiere...' : 'Portfolio analysieren' }}
          </button>
        </div>
      </div>
      <div v-if="portfolioAnalysis" class="ai-box markdown" v-html="md.render(portfolioAnalysis)"></div>
      <div v-else-if="portfolioAnalysisRunning" class="ai-box" style="display: flex; align-items: center; gap: 10px; color: var(--text-tertiary)">
        <span class="spinner" /> Agent sammelt Daten...
      </div>
      <p v-else style="color: var(--text-tertiary); font-size: 13px">
        Klicke auf "Portfolio analysieren" um eine KI-Gesamtanalyse zu starten. Der Agent führt einen vollständigen Data-Science-Prozess durch.
      </p>
      <div v-if="rebalanceText" class="ai-box markdown" style="margin-top: 12px; border-left: 3px solid var(--amber)" v-html="md.render(rebalanceText)"></div>
      <div v-else-if="rebalanceRunning" class="ai-box" style="margin-top: 12px; display: flex; align-items: center; gap: 10px; color: var(--text-tertiary)">
        <span class="spinner" /> Erstelle Rebalancing-Vorschläge...
      </div>
    </div>

    <!-- Individual Stock Analyses -->
    <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px">
      <h2 class="section-title" style="margin: 0">Einzelanalysen</h2>
      <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); cursor: pointer" title="Der Agent ruft sichtbar selbst Tools auf (langsamer)">
        <input type="checkbox" v-model="agenticMode" />
        Agent-Modus (mit Tool-Recherche)
      </label>
    </div>
    <div v-if="portfolio.positions.length === 0" style="color: var(--text-tertiary); font-size: 13px; margin-top: 12px">
      Keine Positionen im Portfolio.
    </div>
    <div
      v-for="pos in portfolio.positions"
      :key="pos.ticker"
      class="card"
      style="margin-bottom: 16px"
    >
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 14px">
        <div>
          <span style="font-weight: 700; font-size: 15px">{{ pos.ticker }}</span>
          <span style="color: var(--text-secondary); margin-left: 8px; font-size: 13px">{{ pos.name }}</span>
          <span class="badge badge-blue" style="margin-left: 8px">{{ pos.sector }}</span>
        </div>
        <div style="display: flex; gap: 16px; align-items: center; font-size: 13px">
          <span>
            Kurs: <strong>$ {{ pos.current_price != null ? fmt(pos.current_price) : '–' }}</strong>
          </span>
          <span v-if="pos.unrealized_pnl_pct != null" :class="pos.unrealized_pnl_pct >= 0 ? 'positive' : 'negative'">
            {{ fmtPct(pos.unrealized_pnl_pct) }}
          </span>
          <button
            class="btn btn-sm"
            @click="summarizeNews(pos.ticker)"
            :disabled="newsSummaryRunning[pos.ticker] || !agentStatus?.ollama_reachable"
            title="KI-Zusammenfassung der aktuellen News"
          >
            <span v-if="newsSummaryRunning[pos.ticker]" class="spinner" /> 📰 News
          </button>
          <button
            class="btn btn-sm btn-primary"
            @click="analyzeStock(pos.ticker)"
            :disabled="analysisRunning[pos.ticker] || !agentStatus?.ollama_reachable"
          >
            <span v-if="analysisRunning[pos.ticker]" class="spinner" />
            {{ analysisRunning[pos.ticker] ? 'Analysiere...' : 'Analysieren' }}
          </button>
        </div>
      </div>

      <template v-if="analysisText[pos.ticker]">
        <div class="ai-box decision-box markdown" v-html="md.render(splitAnalysis(analysisText[pos.ticker] || '').decision)"></div>
        <div v-if="splitAnalysis(analysisText[pos.ticker] || '').agent" class="ai-box markdown" style="margin-top: 10px" v-html="md.render(splitAnalysis(analysisText[pos.ticker] || '').agent)"></div>
      </template>
      <div v-else-if="analysisRunning[pos.ticker]" class="ai-box" style="display: flex; align-items: center; gap: 10px; color: var(--text-tertiary)">
        <span class="spinner" /> Agent läuft: sammelt Daten, berechnet das Ensemble, begründet die Entscheidung...
      </div>

      <div v-if="newsSummary[pos.ticker]" class="ai-box markdown" style="margin-top: 10px; border-left: 3px solid var(--text-tertiary)" v-html="md.render(newsSummary[pos.ticker] || '')"></div>
      <div v-else-if="newsSummaryRunning[pos.ticker]" class="ai-box" style="margin-top: 10px; display: flex; align-items: center; gap: 10px; color: var(--text-tertiary)">
        <span class="spinner" /> Fasse News zusammen...
      </div>
    </div>
  </div>
</template>

<style scoped>
.decision-box {
  border-left: 3px solid var(--blue);
}

/* Rendered Markdown (agent analysis) — overrides the raw pre-wrap of .ai-box */
.markdown { white-space: normal; }
.markdown :deep(h3) {
  font-size: 15px;
  font-weight: 800;
  margin: 18px 0 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
  color: var(--text-primary);
}
.markdown :deep(h3:first-child) { margin-top: 0; }
.markdown :deep(h4) {
  font-size: 13.5px;
  font-weight: 700;
  margin: 14px 0 6px;
  color: var(--blue);
}
.markdown :deep(h5) { font-size: 13px; font-weight: 700; margin: 10px 0 4px; }
.markdown :deep(p) { margin: 6px 0; }
.markdown :deep(ul) { margin: 6px 0 6px; padding-left: 18px; }
.markdown :deep(li) { margin: 4px 0; padding-left: 2px; }
.markdown :deep(li)::marker { color: var(--blue); }
.markdown :deep(strong) { color: var(--text-primary); font-weight: 700; }
.markdown :deep(em) { color: var(--text-secondary); }
.markdown :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 14px 0;
}
</style>
