<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { api } from '@/api/client'
import type { EvalMetrics, Backtest } from '@/types'

const portfolio = usePortfolioStore()

const metrics = ref<EvalMetrics | null>(null)
const backtest = ref<Backtest | null>(null)
const loadingMetrics = ref(false)
const loadingBacktest = ref(false)
const error = ref('')

onMounted(loadMetrics)

async function loadMetrics() {
  loadingMetrics.value = true
  error.value = ''
  try {
    metrics.value = await api.eval.metrics()
  } catch (e: any) {
    error.value = e.message
  } finally {
    loadingMetrics.value = false
  }
}

async function runBacktest() {
  loadingBacktest.value = true
  error.value = ''
  try {
    const tickers = portfolio.positions.map(p => p.ticker)
    backtest.value = await api.eval.backtest(tickers)
  } catch (e: any) {
    error.value = e.message
  } finally {
    loadingBacktest.value = false
  }
}
</script>

<template>
  <div>
    <h2 class="section-title">Eval &amp; Backtest</h2>
    <p style="color: var(--text-secondary); font-size: 13px; margin-bottom: 16px">
      Metriken der KI-Analysen (Faithfulness, Latenz) und Walk-Forward-Backtest des deterministischen Ensembles.
    </p>

    <div v-if="error" class="card" style="color: var(--red); margin-bottom: 12px">{{ error }}</div>

    <div class="card" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
        <h3 style="margin: 0; font-size: 15px">Agent-Metriken</h3>
        <button class="btn btn-sm" :disabled="loadingMetrics" @click="loadMetrics">
          <span v-if="loadingMetrics" class="spinner" /> Aktualisieren
        </button>
      </div>
      <div v-if="metrics" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px">
        <div>
          <div style="font-size: 12px; color: var(--text-secondary)">Runs</div>
          <div style="font-weight: 700">{{ metrics.aggregate.runs }}</div>
        </div>
        <div>
          <div style="font-size: 12px; color: var(--text-secondary)">Faithful Rate</div>
          <div style="font-weight: 700">
            {{ metrics.aggregate.faithful_rate != null ? (metrics.aggregate.faithful_rate * 100).toFixed(0) + '%' : '–' }}
          </div>
        </div>
        <div>
          <div style="font-size: 12px; color: var(--text-secondary)">Ø Latenz</div>
          <div style="font-weight: 700">
            {{ metrics.aggregate.avg_total_ms != null ? metrics.aggregate.avg_total_ms + ' ms' : '–' }}
          </div>
        </div>
        <div>
          <div style="font-size: 12px; color: var(--text-secondary)">Ø Tokens/s</div>
          <div style="font-weight: 700">{{ metrics.aggregate.avg_tokens_per_sec ?? '–' }}</div>
        </div>
      </div>
      <p v-else-if="loadingMetrics" style="color: var(--text-tertiary)">Lade…</p>
    </div>

    <div class="card" style="margin-bottom: 16px; overflow-x: auto">
      <h3 style="margin: 0 0 12px; font-size: 15px">Letzte Analysen</h3>
      <table v-if="metrics?.recent.length" style="width: 100%; font-size: 13px; border-collapse: collapse">
        <thead>
          <tr style="text-align: left; border-bottom: 1px solid var(--border)">
            <th style="padding: 6px">Ticker</th>
            <th>Signal</th>
            <th>Score</th>
            <th>Faithful</th>
            <th>Notizen</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in metrics.recent" :key="r.id" style="border-bottom: 1px solid var(--border)">
            <td style="padding: 6px">{{ r.ticker }}</td>
            <td>{{ r.signal }}</td>
            <td>{{ r.score.toFixed(2) }}</td>
            <td>
              <span v-if="r.faithful === true" class="badge badge-buy">Ja</span>
              <span v-else-if="r.faithful === false" class="badge badge-sell">Nein</span>
              <span v-else>–</span>
            </td>
            <td style="font-size: 11px; color: var(--text-secondary)">{{ r.faithfulness_notes || '–' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else style="color: var(--text-tertiary); font-size: 13px">Noch keine Analysen — starte eine KI-Analyse.</p>
    </div>

    <div class="card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
        <h3 style="margin: 0; font-size: 15px">Ensemble-Backtest</h3>
        <button
          class="btn btn-primary btn-sm"
          :disabled="loadingBacktest || portfolio.positions.length === 0"
          @click="runBacktest"
        >
          <span v-if="loadingBacktest" class="spinner" /> Backtest starten
        </button>
      </div>
      <div v-if="backtest" style="font-size: 13px">
        <p style="color: var(--text-secondary); margin-bottom: 8px">
          Horizont {{ backtest.params.horizon_days }} Tage, Schritt {{ backtest.params.step_days }} Tage
        </p>
        <table style="width: 100%; border-collapse: collapse">
          <thead>
            <tr style="border-bottom: 1px solid var(--border)">
              <th style="padding: 6px; text-align: left">Signal</th>
              <th>n</th>
              <th>Ø Return %</th>
              <th>Hit Rate</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sig in ['BUY', 'HOLD', 'SELL']" :key="sig" style="border-bottom: 1px solid var(--border)">
              <td style="padding: 6px">{{ sig }}</td>
              <td>{{ backtest.aggregate[sig]?.n ?? 0 }}</td>
              <td>{{ backtest.aggregate[sig]?.avg_return_pct ?? '–' }}</td>
              <td>{{ backtest.aggregate[sig]?.hit_rate != null ? (backtest.aggregate[sig].hit_rate! * 100).toFixed(0) + '%' : '–' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else style="color: var(--text-tertiary); font-size: 13px">
        Prüft historisch, ob BUY/HOLD/SELL des Ensembles die Forward-Rendite trifft.
      </p>
    </div>
  </div>
</template>
