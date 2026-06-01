<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { useUiStore } from '@/stores/ui'
import { useFormatters } from '@/composables/useFormatters'
import { useSignal } from '@/composables/useSignal'
import PortfolioCharts from '@/components/PortfolioCharts.vue'
import type { Position } from '@/types'

const portfolio = usePortfolioStore()
const ui = useUiStore()
const { fmt, fmtPct, fmtCurrency, fmtDate } = useFormatters()
const { getSignal } = useSignal()

const bigMovers = computed(() =>
  portfolio.positions.filter(p => Math.abs(p.day_change ?? 0) > 3)
)

// Buy date = earliest "buy" transaction; falls back to when the position was created.
function buyDate(pos: Position): string {
  const buys = (pos.transactions ?? []).filter(t => t.type === 'buy')
  if (buys.length) {
    const earliest = buys.reduce((a, b) => (a.date < b.date ? a : b))
    return fmtDate(earliest.date)
  }
  return pos.created_at ? fmtDate(pos.created_at) : '–'
}
</script>

<template>
  <div>
    <!-- Metric Cards -->
    <div class="grid-4" style="margin-bottom: 20px">
      <div class="metric-card">
        <div class="metric-label">Portfoliowert</div>
        <div class="metric-value">$ {{ fmt(portfolio.stats.total_value) }}</div>
        <div class="metric-sub">{{ portfolio.positions.length }} Positionen</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Tages-P&L</div>
        <div class="metric-value" :class="portfolio.stats.day_pnl >= 0 ? 'positive' : 'negative'">
          {{ portfolio.stats.day_pnl >= 0 ? '+' : '' }}$ {{ fmt(Math.abs(portfolio.stats.day_pnl)) }}
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Gesamt-Rendite</div>
        <div class="metric-value" :class="portfolio.stats.total_ret >= 0 ? 'positive' : 'negative'">
          {{ fmtPct(portfolio.stats.total_ret) }}
        </div>
        <div class="metric-sub" v-if="portfolio.stats.has_cost">
          {{ portfolio.stats.total_pnl >= 0 ? '+' : '' }}$ {{ fmt(Math.abs(portfolio.stats.total_pnl)) }}
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Investiert</div>
        <div class="metric-value">{{ portfolio.stats.has_cost ? fmtCurrency(portfolio.stats.total_cost) : '–' }}</div>
      </div>
    </div>

    <!-- Big Movers Alert -->
    <div v-if="bigMovers.length > 0" class="card" style="margin-bottom: 20px; border-color: var(--amber); background: var(--amber-light)">
      <div style="font-weight: 600; margin-bottom: 8px; color: var(--amber)">Große Bewegungen heute</div>
      <div style="display: flex; flex-wrap: wrap; gap: 8px">
        <span
          v-for="p in bigMovers"
          :key="p.ticker"
          class="badge"
          :class="(p.day_change ?? 0) >= 0 ? 'badge-buy' : 'badge-sell'"
        >
          {{ p.ticker }} {{ fmtPct(p.day_change) }}
        </span>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px">
      <PortfolioCharts />
    </div>

    <!-- Positions Table -->
    <div class="card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px">
        <h2 class="section-title" style="margin: 0">Positionen</h2>
        <button class="btn btn-sm" @click="ui.navigate('positions')">Alle ansehen →</button>
      </div>

      <div v-if="portfolio.positions.length === 0" style="color: var(--text-tertiary); padding: 20px 0; text-align: center">
        Noch keine Positionen. <button class="btn btn-primary btn-sm" @click="ui.openAddModal()" style="margin-left: 8px">+ Position hinzufügen</button>
      </div>

      <div class="table-wrapper" v-else>
        <table class="table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Kurs</th>
              <th>Einstand</th>
              <th>Kaufdatum</th>
              <th>Tagesänderung</th>
              <th>Wert</th>
              <th>Rendite</th>
              <th>G/V ($)</th>
              <th>Signal</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="pos in portfolio.positions" :key="pos.ticker">
              <td>
                <div style="font-weight: 600">{{ pos.ticker }}</div>
                <div style="color: var(--text-tertiary); font-size: 12px">{{ pos.name }}</div>
              </td>
              <td>$ {{ pos.current_price != null ? fmt(pos.current_price) : '–' }}</td>
              <td>{{ (pos.avg_buy_price ?? pos.manual_buy_price) != null ? '$ ' + fmt(pos.avg_buy_price ?? pos.manual_buy_price) : '–' }}</td>
              <td style="color: var(--text-secondary)">{{ buyDate(pos) }}</td>
              <td :class="(pos.day_change ?? 0) >= 0 ? 'positive' : 'negative'">
                {{ fmtPct(pos.day_change) }}
              </td>
              <td>$ {{ pos.current_price != null ? fmt(pos.current_price * pos.shares) : '–' }}</td>
              <td :class="(pos.unrealized_pnl_pct ?? 0) >= 0 ? 'positive' : 'negative'">
                {{ pos.unrealized_pnl_pct != null ? fmtPct(pos.unrealized_pnl_pct) : '–' }}
              </td>
              <td :class="(pos.unrealized_pnl ?? 0) >= 0 ? 'positive' : 'negative'">
                {{ pos.unrealized_pnl != null ? (pos.unrealized_pnl >= 0 ? '+$ ' : '−$ ') + fmt(Math.abs(pos.unrealized_pnl)) : '–' }}
              </td>
              <td>
                <span class="badge" :class="`badge-${getSignal(pos).cls}`">{{ getSignal(pos).label }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.table-wrapper { overflow-x: auto; }
@media (max-width: 768px) {
  .table { display: none; }
}
</style>
