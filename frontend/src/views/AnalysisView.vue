<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { api } from '@/api/client'
import { useFormatters } from '@/composables/useFormatters'
import type { AgentStatus } from '@/types'

const portfolio = usePortfolioStore()
const { fmt, fmtPct } = useFormatters()

const agentStatus = ref<AgentStatus | null>(null)
const statusLoading = ref(false)
const analysisText = ref<Record<string, string>>({})
const analysisRunning = ref<Record<string, boolean>>({})
const portfolioAnalysis = ref('')
const portfolioAnalysisRunning = ref(false)
const pullingModel = ref(false)
const pullLog = ref('')

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

  const source = api.agent.analyzeStock(ticker, portfolio.currentPrices)
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
      <pre v-if="pullLog" style="margin-top: 12px; font-size: 11px; background: var(--bg-secondary); padding: 10px; border-radius: 6px; max-height: 120px; overflow-y: auto">{{ pullLog }}</pre>
    </div>

    <!-- Portfolio Analysis -->
    <div class="card" style="margin-bottom: 20px">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px">
        <h2 class="section-title" style="margin: 0">Portfolio-Analyse</h2>
        <button
          class="btn btn-primary"
          @click="analyzePortfolio"
          :disabled="portfolioAnalysisRunning || !agentStatus?.ollama_reachable"
        >
          <span v-if="portfolioAnalysisRunning" class="spinner" />
          {{ portfolioAnalysisRunning ? 'Analysiere...' : 'Portfolio analysieren' }}
        </button>
      </div>
      <div v-if="portfolioAnalysis" class="ai-box">{{ portfolioAnalysis }}</div>
      <div v-else-if="portfolioAnalysisRunning" class="ai-box" style="display: flex; align-items: center; gap: 10px; color: var(--text-tertiary)">
        <span class="spinner" /> Agent sammelt Daten...
      </div>
      <p v-else style="color: var(--text-tertiary); font-size: 13px">
        Klicke auf "Portfolio analysieren" um eine KI-Gesamtanalyse zu starten. Der Agent führt einen vollständigen Data-Science-Prozess durch.
      </p>
    </div>

    <!-- Individual Stock Analyses -->
    <h2 class="section-title">Einzelanalysen</h2>
    <div v-if="portfolio.positions.length === 0" style="color: var(--text-tertiary); font-size: 13px">
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
            Kurs: <strong>€ {{ pos.current_price != null ? fmt(pos.current_price) : '–' }}</strong>
          </span>
          <span v-if="pos.unrealized_pnl_pct != null" :class="pos.unrealized_pnl_pct >= 0 ? 'positive' : 'negative'">
            {{ fmtPct(pos.unrealized_pnl_pct) }}
          </span>
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

      <div v-if="analysisText[pos.ticker]" class="ai-box">{{ analysisText[pos.ticker] }}</div>
      <div v-else-if="analysisRunning[pos.ticker]" class="ai-box" style="display: flex; align-items: center; gap: 10px; color: var(--text-tertiary)">
        <span class="spinner" /> Agent läuft: ruft Marktdaten ab, berechnet Indikatoren, trainiert Modelle...
      </div>
    </div>
  </div>
</template>
