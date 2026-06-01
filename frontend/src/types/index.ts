export interface Transaction {
  id: number
  ticker: string
  type: 'buy' | 'sell'
  shares: number
  price: number
  date: string
  realized_pnl: number | null
}

export interface Position {
  id: number
  ticker: string
  name: string
  shares: number
  sector: string
  note: string | null
  manual_buy_price: number | null
  alerts_news: boolean
  created_at: string
  transactions: Transaction[]
  // Runtime fields (not from DB, computed client-side)
  current_price?: number
  day_change?: number
  previous_close?: number
  avg_buy_price?: number
  unrealized_pnl?: number
  unrealized_pnl_pct?: number
}

export interface SavingsPlanExecution {
  id: number
  plan_id: number
  date: string
  amount: number
  shares: number
  price: number
}

export interface SavingsPlan {
  id: number
  ticker: string
  monthly_amount: number
  execution_day: number
  history: SavingsPlanExecution[]
}

export interface Quote {
  ticker: string
  current_price: number
  day_change: number
  previous_close: number
  name?: string | null
  sector?: string | null
}

export interface Fundamentals {
  ticker: string
  pe_ratio: number | null
  market_cap: number | null
  eps: number | null
  revenue_growth: number | null
  fifty_two_week_high: number | null
  fifty_two_week_low: number | null
  dividend_yield: number | null
  beta: number | null
  fetched_at: string | null
}

export interface NewsItem {
  id: number
  ticker: string
  headline: string
  summary: string | null
  url: string | null
  source: string | null
  published_at: string
  sentiment: number | null
}

export interface PortfolioStats {
  total_value: number
  total_cost: number
  day_pnl: number
  total_pnl: number
  total_ret: number
  has_cost: boolean
}

export type SignalLabel = 'Verkaufen' | 'Nachkaufen' | 'Beobachten' | 'Halten'
export type SignalClass = 'sell' | 'buy' | 'watch' | 'hold'

export interface Signal {
  label: SignalLabel
  cls: SignalClass
}

export interface AgentStatus {
  ollama_reachable: boolean
  model: string
  model_available: boolean
  available_models?: string[]
  error?: string
}

export interface MetricRow {
  id: number
  ticker: string
  model: string
  signal: string
  score: number
  confidence: number
  total_ms: number | null
  tokens_per_sec: number | null
  eval_tokens: number | null
  faithful: boolean | null
  faithfulness_notes: string | null
  created_at: string
}

export interface EvalMetrics {
  aggregate: {
    runs: number
    avg_tokens_per_sec: number | null
    avg_total_ms: number | null
    faithful_rate: number | null
  }
  recent: MetricRow[]
}

export interface SignalStats {
  n: number
  avg_return_pct: number | null
  hit_rate: number | null
}

export interface Backtest {
  params: { horizon_days: number; step_days: number; min_history: number }
  per_ticker: Record<string, Record<string, SignalStats> | { error: string }>
  aggregate: Record<string, SignalStats>
}
