<script setup lang="ts">
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { usePortfolioStore } from '@/stores/portfolio'
import { useUiStore } from '@/stores/ui'
import { useFormatters } from '@/composables/useFormatters'
import { useSignal } from '@/composables/useSignal'
import type { Transaction } from '@/types'

const portfolio = usePortfolioStore()
const ui = useUiStore()
const { fmt, fmtPct, fmtDate } = useFormatters()
const { getSignal } = useSignal()

// Ticker/name search filter
const search = ref('')
const filteredPositions = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return portfolio.positions
  return portfolio.positions.filter(
    (p) => p.ticker.toLowerCase().includes(q) || (p.name || '').toLowerCase().includes(q),
  )
})

// Deterministic statistics per position (ARIMA + RandomForest, no LLM)
const statResults = ref<Record<string, any>>({})
const statRunning = ref<Record<string, boolean>>({})
async function runStats(ticker: string) {
  if (statRunning.value[ticker]) return
  statRunning.value[ticker] = true
  try {
    statResults.value[ticker] = await api.agent.quickStats(ticker)
  } catch (e: any) {
    statResults.value[ticker] = { ticker, error: e.message }
  } finally {
    statRunning.value[ticker] = false
  }
}
function pct(x: number | null | undefined) {
  return x != null ? `${Math.round(x * 100)}%` : '–'
}

const expandedTicker = ref<string | null>(null)
const showTxModal = ref(false)
const txTicker = ref('')
const txForm = ref({ type: 'buy' as 'buy' | 'sell', shares: '', price: '', date: new Date().toISOString().split('T')[0]! })
const txSaving = ref(false)
const txError = ref('')

function toggleHistory(ticker: string) {
  expandedTicker.value = expandedTicker.value === ticker ? null : ticker
}

function openTxModal(ticker: string) {
  txTicker.value = ticker
  txForm.value = { type: 'buy', shares: '', price: '', date: new Date().toISOString().split('T')[0]! }
  txError.value = ''
  showTxModal.value = true
}

async function submitTransaction() {
  if (!txForm.value.shares || !txForm.value.price) { txError.value = 'Alle Felder ausfüllen'; return }
  txSaving.value = true
  txError.value = ''
  try {
    await portfolio.addTransaction(txTicker.value, {
      type: txForm.value.type,
      shares: parseFloat(txForm.value.shares),
      price: parseFloat(txForm.value.price),
      date: txForm.value.date,
      realized_pnl: null,
    })
    showTxModal.value = false
  } catch (e: any) {
    txError.value = e.message
  } finally {
    txSaving.value = false
  }
}

async function removePosition(ticker: string) {
  if (!confirm(`Position ${ticker} wirklich löschen?`)) return
  await portfolio.removePosition(ticker)
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px">
      <h1 class="section-title" style="margin: 0">Positionen ({{ portfolio.positions.length }})</h1>
      <button class="btn btn-primary" @click="ui.openAddModal()">+ Position hinzufügen</button>
    </div>

    <input
      v-model="search"
      placeholder="🔍 Suche nach Ticker oder Name…"
      style="width: 100%; padding: 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 14px; margin-bottom: 16px"
    />

    <div v-if="portfolio.positions.length === 0" class="card" style="text-align: center; padding: 40px; color: var(--text-tertiary)">
      Noch keine Positionen.
    </div>
    <div v-else-if="filteredPositions.length === 0" class="card" style="text-align: center; padding: 24px; color: var(--text-tertiary)">
      Keine Treffer für diese Suche.
    </div>

    <div v-for="pos in filteredPositions" :key="pos.ticker" class="card" style="margin-bottom: 14px">
      <!-- Position Header -->
      <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
        <div>
          <span style="font-size: 18px; font-weight: 800">{{ pos.ticker }}</span>
          <span style="color: var(--text-secondary); margin-left: 10px">{{ pos.name }}</span>
          <span class="badge badge-blue" style="margin-left: 8px">{{ pos.sector }}</span>
        </div>
        <span class="badge" :class="`badge-${getSignal(pos).cls}`">{{ getSignal(pos).label }}</span>
      </div>

      <!-- Metrics Row -->
      <div class="grid-4" style="margin: 14px 0">
        <div class="metric-card">
          <div class="metric-label">Kurs</div>
          <div class="metric-value" style="font-size: 16px">$ {{ pos.current_price != null ? fmt(pos.current_price) : '–' }}</div>
          <div class="metric-sub" :class="(pos.day_change ?? 0) >= 0 ? 'positive' : 'negative'">{{ fmtPct(pos.day_change) }} heute</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Anzahl</div>
          <div class="metric-value" style="font-size: 16px">{{ pos.shares }}</div>
          <div class="metric-sub">Ø Kauf: {{ pos.avg_buy_price != null ? `$ ${fmt(pos.avg_buy_price)}` : '–' }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Wert</div>
          <div class="metric-value" style="font-size: 16px">$ {{ pos.current_price != null ? fmt(pos.current_price * pos.shares) : '–' }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Rendite</div>
          <div class="metric-value" style="font-size: 16px" :class="(pos.unrealized_pnl_pct ?? 0) >= 0 ? 'positive' : 'negative'">
            {{ pos.unrealized_pnl_pct != null ? fmtPct(pos.unrealized_pnl_pct) : '–' }}
          </div>
          <div class="metric-sub" :class="(pos.unrealized_pnl ?? 0) >= 0 ? 'positive' : 'negative'">
            {{ pos.unrealized_pnl != null ? `$ ${fmt(pos.unrealized_pnl)}` : '' }}
          </div>
        </div>
      </div>

      <!-- Action Buttons -->
      <div style="display: flex; gap: 8px; flex-wrap: wrap">
        <button class="btn btn-sm btn-primary" @click="openTxModal(pos.ticker)">+ Transaktion</button>
        <button class="btn btn-sm" @click="runStats(pos.ticker)" :disabled="statRunning[pos.ticker]">
          <span v-if="statRunning[pos.ticker]" class="spinner" /> 📊 Statistik
        </button>
        <button class="btn btn-sm" @click="toggleHistory(pos.ticker)">
          {{ expandedTicker === pos.ticker ? 'Verlauf ausblenden' : 'Verlauf' }}
          ({{ pos.transactions?.length ?? 0 }})
        </button>
        <button class="btn btn-sm" @click="ui.navigate('chat')">KI-Agent</button>
        <button class="btn btn-sm btn-danger" @click="removePosition(pos.ticker)">Löschen</button>
      </div>

      <!-- Deterministic statistics (ARIMA + RandomForest), no LLM -->
      <div v-if="statResults[pos.ticker]" class="card" style="margin-top: 12px; background: var(--bg-secondary); font-size: 13px">
        <template v-if="statResults[pos.ticker].error">
          <span style="color: var(--red)">{{ statResults[pos.ticker].error }}</span>
        </template>
        <template v-else>
          <div style="font-weight: 700; margin-bottom: 6px">📊 Statistik (deterministisch, ohne LLM)</div>
          <div>
            <strong>ARIMA:</strong> {{ statResults[pos.ticker].arima.signal }}
            (Konfidenz {{ pct(statResults[pos.ticker].arima.confidence) }})
            <span v-if="statResults[pos.ticker].arima.forecast_30d">· 30T-Prognose $ {{ statResults[pos.ticker].arima.forecast_30d }}</span>
          </div>
          <div>
            <strong>Random Forest:</strong> {{ statResults[pos.ticker].random_forest.signal }}
            (Konfidenz {{ pct(statResults[pos.ticker].random_forest.confidence) }})
          </div>
          <div style="color: var(--text-tertiary); margin-top: 4px; font-size: 12px">{{ statResults[pos.ticker].random_forest.details }}</div>
        </template>
      </div>

      <!-- Transaction History -->
      <div v-if="expandedTicker === pos.ticker && pos.transactions?.length" style="margin-top: 16px; border-top: 1px solid var(--border); padding-top: 14px">
        <div style="font-weight: 600; font-size: 13px; margin-bottom: 10px">Transaktionsverlauf</div>
        <table class="table">
          <thead>
            <tr><th>Datum</th><th>Typ</th><th>Aktien</th><th>Kurs</th><th>Gesamt</th><th>P&L</th></tr>
          </thead>
          <tbody>
            <tr v-for="tx in [...pos.transactions].reverse()" :key="tx.id">
              <td>{{ fmtDate(tx.date) }}</td>
              <td><span class="badge" :class="tx.type === 'buy' ? 'badge-buy' : 'badge-sell'">{{ tx.type === 'buy' ? 'Kauf' : 'Verkauf' }}</span></td>
              <td>{{ tx.shares }}</td>
              <td>$ {{ fmt(tx.price) }}</td>
              <td>$ {{ fmt(tx.shares * tx.price) }}</td>
              <td :class="tx.realized_pnl != null ? (tx.realized_pnl >= 0 ? 'positive' : 'negative') : ''">
                {{ tx.realized_pnl != null ? `$ ${fmt(tx.realized_pnl)}` : '–' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Transaction Modal -->
    <div v-if="showTxModal" class="modal-overlay" @click.self="showTxModal = false">
      <div class="modal">
        <h2 class="modal-title">Transaktion: {{ txTicker }}</h2>
        <div class="form-group">
          <label class="form-label">Typ</label>
          <div style="display: flex; gap: 8px">
            <button class="btn" :class="{ 'btn-primary': txForm.type === 'buy' }" @click="txForm.type = 'buy'">Kauf</button>
            <button class="btn" :class="{ 'btn-danger': txForm.type === 'sell' }" @click="txForm.type = 'sell'">Verkauf</button>
          </div>
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">Anzahl Aktien</label>
            <input v-model="txForm.shares" class="form-input" type="number" step="0.0001" placeholder="0" />
          </div>
          <div class="form-group">
            <label class="form-label">Kurs ($)</label>
            <input v-model="txForm.price" class="form-input" type="number" step="0.01" placeholder="0.00" />
          </div>
        </div>
        <div class="form-group">
          <label class="form-label">Datum</label>
          <input v-model="txForm.date" class="form-input" type="date" />
        </div>
        <p v-if="txError" style="color: var(--red); font-size: 13px; margin-bottom: 8px">{{ txError }}</p>
        <div class="modal-footer">
          <button class="btn" @click="showTxModal = false">Abbrechen</button>
          <button class="btn btn-primary" @click="submitTransaction" :disabled="txSaving">
            <span v-if="txSaving" class="spinner" /> Speichern
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
