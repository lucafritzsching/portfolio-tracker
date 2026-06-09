import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { Position, SavingsPlan, PortfolioStats, Transaction } from '@/types'

export const usePortfolioStore = defineStore('portfolio', () => {
  const positions = ref<Position[]>([])
  const savingsPlans = ref<SavingsPlan[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ── Computed stats ──────────────────────────────────────────────────────────

  const stats = computed<PortfolioStats>(() => {
    let total_value = 0
    let total_cost = 0
    let day_pnl = 0
    let has_cost = false

    for (const pos of positions.value) {
      const value = (pos.current_price ?? 0) * pos.shares
      total_value += value

      const prev_close = pos.previous_close ?? pos.current_price ?? 0
      day_pnl += ((pos.current_price ?? 0) - prev_close) * pos.shares

      const avg = pos.avg_buy_price ?? pos.manual_buy_price
      if (avg != null) {
        total_cost += avg * pos.shares
        has_cost = true
      }
    }

    const total_pnl = has_cost ? total_value - total_cost : 0
    const total_ret = has_cost && total_cost > 0 ? (total_pnl / total_cost) * 100 : 0

    return { total_value, total_cost, day_pnl, total_pnl, total_ret, has_cost }
  })

  const currentPrices = computed<Record<string, number>>(() => {
    const result: Record<string, number> = {}
    for (const pos of positions.value) {
      if (pos.current_price != null) result[pos.ticker] = pos.current_price
    }
    return result
  })

  // ── Actions ─────────────────────────────────────────────────────────────────

  async function loadPositions() {
    loading.value = true
    error.value = null
    try {
      const raw = await api.positions.list()
      positions.value = raw.map(enrichPosition)
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function refreshQuotes() {
    if (positions.value.length === 0) return
    loading.value = true
    try {
      const tickers = positions.value.map(p => p.ticker)
      const quotes = await api.quotes.batch(tickers)
      positions.value = positions.value.map(pos => {
        const q = quotes[pos.ticker]
        if (!q) return pos
        return enrichPosition({
          ...pos,
          current_price: q.current_price,
          day_change: q.day_change,
          previous_close: q.previous_close,
        })
      })
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function addPosition(data: {
    ticker: string
    name: string
    sector: string
    shares?: number
    buyPrice?: number
    note?: string
  }) {
    const pos = await api.positions.create({
      ticker: data.ticker,
      name: data.name,
      sector: data.sector,
      shares: 0,
    })

    if (data.buyPrice && data.shares) {
      await api.transactions.add(data.ticker, {
        type: 'buy',
        shares: data.shares,
        price: data.buyPrice,
        date: new Date().toISOString().split('T')[0]!,
        realized_pnl: null,
      })
    }

    await loadPositions()
    await refreshQuotes()
  }

  async function updatePosition(ticker: string, updates: Partial<Position>) {
    await api.positions.update(ticker, updates)
    await loadPositions()
  }

  async function removePosition(ticker: string) {
    await api.positions.delete(ticker)
    positions.value = positions.value.filter(p => p.ticker !== ticker)
  }

  async function addTransaction(ticker: string, tx: Omit<Transaction, 'id' | 'ticker'>) {
    await api.transactions.add(ticker, tx)
    await loadPositions()
    await refreshQuotes()
  }

  async function loadSavingsPlans() {
    savingsPlans.value = await api.savingsPlans.list()
  }

  async function addSavingsPlan(data: { ticker: string; monthly_amount: number; execution_day: number }) {
    await api.savingsPlans.create(data)
    await loadSavingsPlans()
  }

  async function removeSavingsPlan(id: number) {
    await api.savingsPlans.delete(id)
    savingsPlans.value = savingsPlans.value.filter(p => p.id !== id)
  }

  async function executeSavingsPlan(id: number) {
    const plan = savingsPlans.value.find(p => p.id === id)
    if (!plan) return
    const price = currentPrices.value[plan.ticker] ?? 0
    if (!price) throw new Error('Kein aktueller Kurs für ' + plan.ticker)
    await api.savingsPlans.execute(id, price)
    await loadSavingsPlans()
    await loadPositions()
  }

  return {
    positions,
    savingsPlans,
    loading,
    error,
    stats,
    currentPrices,
    loadPositions,
    refreshQuotes,
    addPosition,
    updatePosition,
    removePosition,
    addTransaction,
    loadSavingsPlans,
    addSavingsPlan,
    removeSavingsPlan,
    executeSavingsPlan,
  }
})

function calcAvgBuyPrice(transactions: Transaction[]): number | undefined {
  const buys = transactions.filter(t => t.type === 'buy')
  if (buys.length === 0) return undefined
  const totalCost = buys.reduce((sum, t) => sum + t.shares * t.price, 0)
  const totalShares = buys.reduce((sum, t) => sum + t.shares, 0)
  return totalShares > 0 ? totalCost / totalShares : undefined
}

function enrichPosition(pos: Position): Position {
  const avg = pos.manual_buy_price ?? calcAvgBuyPrice(pos.transactions ?? [])
  const unrealized_pnl =
    avg != null && pos.current_price != null
      ? (pos.current_price - avg) * pos.shares
      : undefined
  const unrealized_pnl_pct =
    avg != null && pos.current_price != null && avg > 0
      ? ((pos.current_price - avg) / avg) * 100
      : undefined

  return { ...pos, avg_buy_price: avg, unrealized_pnl, unrealized_pnl_pct }
}
