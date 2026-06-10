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

export interface ScreenerScoreBreakdown {
  label: string
  points: number
  max_points: number
  passed: boolean
  detail: string
}

export interface ScreenerAgentAnalysis {
  turnaround_story: boolean
  positive_events: string[]
  risks: string[]
  signal_quality: string[]
  why_interesting: string
}

export interface ScreenerResearchPoint {
  text: string
  evidence: string
  evidence_quote: string
}

export interface ScreenerInsiderBuyerSummary {
  name: string
  total_value: number
  buy_count: number
}

export interface ScreenerInsiderContext {
  recent_count: number
  context_count: number
  total_value: number
  top_buyers: ScreenerInsiderBuyerSummary[]
  summary: string
}

export interface ScreenerUpcomingCatalyst {
  catalyst_type: string
  date_text: string
  detail: string
  evidence: string
  evidence_quote: string
}

export interface ScreenerEventTimelineItem {
  event_date: string
  title: string
  event_type: string
  source: string
  evidence: string
  evidence_quote: string
}

export interface ScreenerRiskSignal {
  label: string
  detail: string
  evidence: string
  evidence_quote: string
}

export interface ScreenerResearchBrief {
  bull_case: ScreenerResearchPoint[]
  bear_case: ScreenerResearchPoint[]
  insider_context: ScreenerInsiderContext
  upcoming_catalysts: ScreenerUpcomingCatalyst[]
  event_timeline: ScreenerEventTimelineItem[]
  risk_signals: ScreenerRiskSignal[]
}

export interface ScreenerScore {
  strategy: string
  score: number
  label: string
  reasons: string[]
  evidence: string[]
  performance_90d: number | null
  turnaround_news: string[]
  score_breakdown: ScreenerScoreBreakdown[]
  decision_log: string[]
  qualifies: boolean
  agent_analysis: ScreenerAgentAnalysis | null
  biotech_events: string[]
  story_de: string
  evidence_quote: string
  used_llm: boolean
  event_type: string
  event_strength: number
  event_evidence: string
}

export interface ScreenerFiling {
  filing_date: string
  event_type: string
  url: string
}

export interface ScreenerInsiderBuy {
  name: string
  transaction_date: string | null
  filing_date: string | null
  shares: number
  price: number | null
  value: number | null
}

export interface ScreenerCandidate {
  ticker: string
  name: string
  exchange: string
  industry: string
  market_cap: number | null
  revenue_growth: number | null
  performance_90d: number | null
  alt_a: ScreenerScore
  alt_b: ScreenerScore
  turnaround_news: string[]
  insider_buys: ScreenerInsiderBuy[]
  insider_context_buys: ScreenerInsiderBuy[]
  biotech_events: string[]
  risk_flags: string[]
  sec_filings: ScreenerFiling[]
  research: ScreenerResearchBrief
}

export interface ScreenerFunnelStep {
  label: string
  count: number
  detail: string
}

export interface ScreenerWindows {
  event_days: number
  context_days: number
  insider_context_days: number
}

export interface ScreenerResponse {
  universe_count: number
  filter_funnel: ScreenerFunnelStep[]
  windows: ScreenerWindows
  candidates: ScreenerCandidate[]
  created_at: string | null
  universe_source: 'live' | 'kuratiert'
  universe_updated_at: string | null
}

export interface ScreenerUniverseStatus {
  count: number
  updated_at: string | null
  source: 'live' | 'kuratiert'
}

export interface ScreenerScanProgress {
  stage: string
  i: number
  n: number
  ticker: string
}
