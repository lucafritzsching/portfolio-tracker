import type {
  Position, Transaction, SavingsPlan, Quote, Fundamentals, NewsItem, AgentStatus,
  EvalMetrics, Backtest,
} from '@/types'

const BASE = 'http://localhost:8000/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail || `HTTP ${resp.status}`)
  }
  return resp.json()
}

// ── Portfolio ─────────────────────────────────────────────────────────────────

export const api = {
  positions: {
    list: () => request<Position[]>('/portfolio/positions'),
    create: (body: Partial<Position>) =>
      request<Position>('/portfolio/positions', { method: 'POST', body: JSON.stringify(body) }),
    update: (ticker: string, body: Partial<Position>) =>
      request<Position>(`/portfolio/positions/${ticker}`, { method: 'PATCH', body: JSON.stringify(body) }),
    delete: (ticker: string) =>
      fetch(`${BASE}/portfolio/positions/${ticker}`, { method: 'DELETE' }),
  },

  transactions: {
    add: (ticker: string, body: Omit<Transaction, 'id' | 'ticker'>) =>
      request<Transaction>(`/portfolio/positions/${ticker}/transactions`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    list: (ticker: string) =>
      request<Transaction[]>(`/portfolio/positions/${ticker}/transactions`),
  },

  savingsPlans: {
    list: () => request<SavingsPlan[]>('/portfolio/savings-plans'),
    create: (body: Partial<SavingsPlan>) =>
      request<SavingsPlan>('/portfolio/savings-plans', { method: 'POST', body: JSON.stringify(body) }),
    delete: (id: number) =>
      fetch(`${BASE}/portfolio/savings-plans/${id}`, { method: 'DELETE' }),
    execute: (id: number, currentPrice: number) =>
      request<SavingsPlan>(`/portfolio/savings-plans/${id}/execute?current_price=${currentPrice}`, { method: 'POST' }),
  },

  // ── Quotes ──────────────────────────────────────────────────────────────────

  quotes: {
    get: (ticker: string) => request<Quote>(`/quotes/${ticker}`),
    batch: (tickers: string[]) =>
      request<Record<string, Omit<Quote, 'ticker'>>>(`/quotes/batch/quotes?tickers=${tickers.join(',')}`),
  },

  // ── Market Data ─────────────────────────────────────────────────────────────

  marketData: {
    history: (ticker: string, period = '1y') =>
      request<any[]>(`/market-data/history/${ticker}?period=${period}`),
    fundamentals: (ticker: string) =>
      request<Fundamentals>(`/market-data/fundamentals/${ticker}`),
    news: (ticker: string, days = 7) =>
      request<NewsItem[]>(`/market-data/news/${ticker}?days=${days}`),
    warmup: () =>
      request<{ warmed_up: number; details: Record<string, unknown> }>(
        '/market-data/warmup', { method: 'POST' },
      ),
  },

  // ── Agent ────────────────────────────────────────────────────────────────────

  agent: {
    status: () => request<AgentStatus>('/agent/status'),
    pullModel: () => fetch(`${BASE}/agent/pull-model`, { method: 'POST' }),

    // Unified routing agent: one free-text question → the LLM routes to the right tool
    // (strategy screen / NL-news judgment / statistics) → visible tool-trace + explanation (SSE).
    ask: (question: string, currentPrices: Record<string, number>): EventSource => {
      const p = encodeURIComponent(JSON.stringify(currentPrices))
      return new EventSource(`${BASE}/agent/ask?question=${encodeURIComponent(question)}&current_prices=${p}`)
    },
  },

  // ── Eval ──────────────────────────────────────────────────────────────────────

  eval: {
    metrics: () => request<EvalMetrics>('/eval/metrics'),
    backtest: (tickers: string[] = [], horizon = 20, step = 5) => {
      const t = tickers.length ? `&tickers=${tickers.join(',')}` : ''
      return request<Backtest>(`/eval/backtest?horizon=${horizon}&step=${step}${t}`)
    },
  },

  // ── Import ────────────────────────────────────────────────────────────────────

  import: (payload: { positions: any[]; transactions: any[] }) =>
    request<{ imported_positions: number; imported_transactions: number }>('/portfolio/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
