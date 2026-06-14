<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type {
  ScreenerCandidate, ScreenerInsiderBuy, ScreenerResponse,
  ScreenerScanProgress, ScreenerUniverseStatus,
} from '@/types'

const result = ref<ScreenerResponse | null>(null)
const loading = ref(false)
const error = ref('')
const minScore = ref(0)
const loadedMinScore = ref<number | null>(null)

const scanning = ref(false)
const scanProgress = ref<ScreenerScanProgress | null>(null)
const universe = ref<ScreenerUniverseStatus | null>(null)
const refreshingUniverse = ref(false)
const universeProgress = ref<ScreenerScanProgress | null>(null)
let scanSource: EventSource | null = null
let universeSource: EventSource | null = null

const candidates = computed(() => result.value?.candidates ?? [])
const topCandidate = computed(() => candidates.value[0] ?? null)
const signalStep = computed(() =>
  result.value?.filter_funnel.find(step => step.label === '7-Tage-Signal') ?? null,
)
const baseStep = computed(() =>
  result.value?.filter_funnel.find(step => step.label === 'Umsatz ok (inkl. Pre-Revenue)') ?? null,
)
const scoreStep = computed(() =>
  result.value?.filter_funnel.find(step => step.label === 'Score-Filter') ?? null,
)
const initialLoading = computed(() => loading.value && !result.value)

onMounted(() => {
  loadLatest()
  loadUniverse()
})

onBeforeUnmount(() => {
  scanSource?.close()
  universeSource?.close()
})

async function loadLatest() {
  loading.value = true
  error.value = ''
  try {
    const latest = await api.screener.latest()
    if (latest.created_at) result.value = latest
  } catch (e: any) {
    error.value = e.message || 'Letzter Scan konnte nicht geladen werden.'
  } finally {
    loading.value = false
  }
}

async function loadUniverse() {
  try {
    universe.value = await api.screener.universe()
  } catch {
    universe.value = null
  }
}

function startScan() {
  if (scanning.value) return
  scanning.value = true
  error.value = ''
  scanProgress.value = null
  const requestedMinScore = minScore.value
  scanSource = api.screener.scan(12, requestedMinScore)
  scanSource.onmessage = (msg) => {
    if (msg.data === '[DONE]') {
      scanSource?.close()
      scanSource = null
      scanning.value = false
      scanProgress.value = null
      return
    }
    try {
      const event = JSON.parse(msg.data)
      if (event.stage) scanProgress.value = event
      if (event.result) {
        result.value = event.result
        loadedMinScore.value = requestedMinScore
      }
      if (event.error) error.value = event.error
    } catch { /* unbekanntes Event ignorieren */ }
  }
  scanSource.onerror = () => {
    scanSource?.close()
    scanSource = null
    scanning.value = false
    scanProgress.value = null
    if (!result.value) error.value = 'Verbindung zum Scan abgebrochen.'
  }
}

function refreshUniverse() {
  if (refreshingUniverse.value) return
  const ok = window.confirm(
    'Universum neu laden? Der NASDAQ-Stock-Screener liefert alle Biotech/Pharma-Titel in wenigen Sekunden.',
  )
  if (!ok) return
  refreshingUniverse.value = true
  universeProgress.value = null
  universeSource = api.screener.universeRefresh()
  universeSource.onmessage = (msg) => {
    if (msg.data === '[DONE]') {
      universeSource?.close()
      universeSource = null
      refreshingUniverse.value = false
      universeProgress.value = null
      loadUniverse()
      return
    }
    try {
      const event = JSON.parse(msg.data)
      if (event.stage) universeProgress.value = event
      if (event.error) error.value = event.error
    } catch { /* ignorieren */ }
  }
  universeSource.onerror = () => {
    universeSource?.close()
    universeSource = null
    refreshingUniverse.value = false
    universeProgress.value = null
  }
}

function fmtTimestamp(value: string | null | undefined): string {
  if (!value) return '-'
  const d = new Date(value)
  return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatRatio(value: number | null | undefined): string {
  if (value == null) return '-'
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

function formatMarketCap(value: number | null | undefined): string {
  if (value == null) return '-'
  if (Math.abs(value) >= 1e9) return `$ ${(value / 1e9).toFixed(2)} Mrd.`
  if (Math.abs(value) >= 1e6) return `$ ${(value / 1e6).toFixed(0)} Mio.`
  return `$ ${value.toLocaleString('de-DE')}`
}

function formatMoney(value: number | null | undefined): string {
  if (value == null) return '-'
  return `$ ${value.toLocaleString('de-DE', { maximumFractionDigits: 0 })}`
}

function scoreClass(candidate: ScreenerCandidate): string {
  if (candidate.alt_b.score >= 80) return 'strong'
  if (candidate.alt_b.qualifies) return 'watch'
  return 'muted'
}

function insiderSummary(buys: ScreenerInsiderBuy[]): string {
  if (!buys.length) return 'Keine qualifizierten Käufe'
  const total = buys.reduce((sum, buy) => sum + (buy.value ?? 0), 0)
  const names = buys.slice(0, 2).map(buy => buy.name).join(', ')
  return `${buys.length} Kauf/Käufe, ${formatMoney(total)}${names ? `, ${names}` : ''}`
}
</script>

<template>
  <div class="screener-view">
    <div class="view-toolbar">
      <div>
        <h1 class="section-title">Alt B Scanner</h1>
        <p class="view-subtitle">
          NASDAQ · Biotechnologie · Market Cap ≤ 15 Mrd. · Umsatz ok (inkl. Pre-Revenue) · 8-K/Insider/News 7 Tage
        </p>
        <p v-if="result?.created_at" class="run-meta">
          Letzter Scan: {{ fmtTimestamp(result.created_at) }}
        </p>
      </div>
      <div class="toolbar-actions">
        <span v-if="universe" class="universe-chip" :title="universe.source === 'live'
          ? (universe.count ? `Gecrawltes Universum, Stand ${fmtTimestamp(universe.updated_at)}` : 'Noch kein gecachtes Universum — bitte aktualisieren')
          : 'Alter kuratierter Lauf — bitte Universum aktualisieren'">
          Universum: {{ universe.count || 'nicht aufgebaut' }}
        </span>
        <button class="btn" :disabled="refreshingUniverse || scanning" @click="refreshUniverse">
          <span v-if="refreshingUniverse" class="spinner" />
          Universum aktualisieren
        </button>
        <select v-model.number="minScore" class="form-input score-select" :disabled="scanning">
          <option :value="0">Score 0+</option>
          <option :value="50">Score 50+</option>
          <option :value="75">Score 75+</option>
        </select>
        <button class="btn btn-primary" :disabled="scanning || refreshingUniverse" @click="startScan">
          <span v-if="scanning" class="spinner" />
          Scan starten
        </button>
      </div>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="scanning" class="progress-box">
      <span class="spinner" />
      <template v-if="scanProgress">
        {{ scanProgress.stage }}: {{ scanProgress.ticker }} ({{ scanProgress.i }}/{{ scanProgress.n }})
      </template>
      <template v-else>Scan läuft an…</template>
    </div>

    <div v-if="refreshingUniverse" class="progress-box">
      <span class="spinner" />
      <template v-if="universeProgress">
        Universum-Crawl: {{ universeProgress.ticker }} ({{ universeProgress.i }}/{{ universeProgress.n }})
      </template>
      <template v-else>Universum-Crawl läuft an…</template>
    </div>

    <div v-if="result" class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">Universum</div>
        <div class="metric-value">{{ result.universe_count }}</div>
        <div class="metric-sub">
          {{ result.universe_count ? 'gecrawlte NASDAQ-Biotech-Ticker' : 'Universum noch nicht aufgebaut' }}
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-label">7-Tage-Signale</div>
        <div class="metric-value">{{ signalStep?.count ?? 0 }}</div>
        <div class="metric-sub">starkes Event oder Insider-Kauf</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Treffer</div>
        <div class="metric-value">{{ candidates.length }}</div>
        <div class="metric-sub">nach Score-Filter und Limit</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Top Alt B</div>
        <div class="metric-value">{{ topCandidate ? `${topCandidate.ticker} ${topCandidate.alt_b.score}` : '-' }}</div>
        <div class="metric-sub">Score von 100</div>
      </div>
    </div>

    <div v-if="result" class="funnel">
      <div v-for="step in result.filter_funnel" :key="step.label" class="funnel-step">
        <span class="funnel-count">{{ step.count }}</span>
        <span class="funnel-label">{{ step.label }}</span>
        <span class="funnel-detail">{{ step.detail }}</span>
      </div>
    </div>

    <div v-if="!result && !loading && !scanning" class="state-box">
      Noch kein Scan gespeichert. Starte den ersten Scan — der Fortschritt wird live angezeigt
      und das Ergebnis bleibt gespeichert.
    </div>

    <div v-if="initialLoading" class="state-box">
      <span class="spinner" />
      Letzter Scan wird geladen...
    </div>

    <div v-else-if="result && candidates.length === 0" class="empty-state">
      <div class="empty-head">
        <div>
          <h2>Keine Alt-B-Treffer im aktuellen Fenster</h2>
          <p>
            Der Screener arbeitet: {{ baseStep?.count ?? 0 }} Unternehmen erfüllen die harten Basisfilter,
            aber aktuell erfüllt keines das 7-Tage-Signal.
          </p>
        </div>
        <span v-if="loading" class="refresh-badge">
          <span class="spinner" />
          Aktualisiert
        </span>
      </div>

      <div class="empty-grid">
        <div>
          <span>Basisfilter</span>
          <strong>{{ baseStep?.count ?? 0 }}</strong>
          <p>NASDAQ, Biotech, Market Cap und Umsatz (inkl. Pre-Revenue) passen.</p>
        </div>
        <div>
          <span>Turnaround-Signal</span>
          <strong>{{ signalStep?.count ?? 0 }}</strong>
          <p>Kein starkes Event ab Stärke 3 und kein qualifizierter Insider-Kauf.</p>
        </div>
        <div>
          <span>Score-Filter</span>
          <strong>{{ scoreStep?.count ?? 0 }}</strong>
          <p>Geladener Score-Filter: {{ loadedMinScore ?? minScore }}+.</p>
        </div>
      </div>

      <ul class="empty-reasons">
        <li>Analystenmeinungen, Kursziele, reine Marktkommentare und Routine-Präsentationen zählen bewusst nicht.</li>
        <li>Alt B zeigt hier echte Screening-Wirkung: Die Basisfilter lassen Kandidaten übrig, das Event-Gate blockt sie.</li>
        <li>Für die Präsentation ist das ein valider Befund: aktuell keine belastbare Turnaround-Story im 7-Tage-Fenster.</li>
      </ul>
    </div>

    <section v-else-if="candidates.length" class="candidate-list">
      <article v-for="candidate in candidates" :key="candidate.ticker" class="candidate-card">
        <header class="candidate-header">
          <div>
            <div class="ticker-row">
              <h2>{{ candidate.ticker }}</h2>
              <span class="badge badge-blue">{{ candidate.alt_b.label }}</span>
            </div>
            <p>{{ candidate.name }}</p>
          </div>
          <div class="score-pill" :class="scoreClass(candidate)">
            <strong>{{ candidate.alt_b.score }}</strong>
            <span>/100</span>
          </div>
        </header>

        <div class="candidate-meta">
          <span>Market Cap {{ formatMarketCap(candidate.market_cap) }}</span>
          <span>Umsatzwachstum {{ formatRatio(candidate.revenue_growth) }}</span>
          <span>90 Tage {{ formatRatio(candidate.performance_90d) }}</span>
          <span>{{ candidate.exchange }} · {{ candidate.industry }}</span>
        </div>

        <div class="event-strip">
          <div>
            <span class="evidence-label">Event-Typ</span>
            <strong>{{ candidate.alt_b.event_type || (candidate.turnaround_news.length ? 'Neu scannen für Event-Typ' : 'Insider-Signal') }}</strong>
          </div>
          <div>
            <span class="evidence-label">Event-Stärke</span>
            <strong>{{ candidate.alt_b.event_strength ? `${candidate.alt_b.event_strength}/5` : '-' }}</strong>
          </div>
          <div>
            <span class="evidence-label">News X</span>
            <strong>{{ candidate.alt_b.event_evidence || candidate.turnaround_news[0] || 'Kein News-Gate' }}</strong>
          </div>
        </div>

        <div v-if="candidate.alt_b.story_de" class="story-panel">
          <h3>Turnaround-Story <span class="badge badge-blue">KI</span></h3>
          <p>{{ candidate.alt_b.story_de }}</p>
          <blockquote v-if="candidate.alt_b.evidence_quote">
            „{{ candidate.alt_b.evidence_quote }}"
          </blockquote>
        </div>

        <div v-if="candidate.sec_filings.length" class="filings-row">
          <a
            v-for="filing in candidate.sec_filings"
            :key="filing.url"
            :href="filing.url"
            target="_blank"
            rel="noopener"
            class="filing-chip"
          >
            8-K {{ filing.filing_date }} · {{ filing.event_type }}
          </a>
        </div>

        <div class="analysis-grid research-grid">
          <div class="analysis-panel">
            <h3>Bull Case</h3>
            <ul v-if="candidate.research.bull_case.length" class="research-list">
              <li v-for="point in candidate.research.bull_case" :key="point.text">
                <strong>{{ point.text }}</strong>
                <small>Beleg: {{ point.evidence_quote || point.evidence }}</small>
              </li>
            </ul>
            <p v-else>Kein belegter Bull Case aus den verfügbaren Daten.</p>
          </div>

          <div class="analysis-panel">
            <h3>Bear Case</h3>
            <ul v-if="candidate.research.bear_case.length" class="research-list">
              <li v-for="point in candidate.research.bear_case" :key="point.text">
                <strong>{{ point.text }}</strong>
                <small>Beleg: {{ point.evidence_quote || point.evidence }}</small>
              </li>
            </ul>
            <p v-else>Kein belegter Bear Case aus den verfügbaren Daten.</p>
          </div>

          <div class="analysis-panel">
            <h3>Insider 7 Tage</h3>
            <p>{{ insiderSummary(candidate.insider_buys) }}</p>
            <h3 class="subhead">Insider 180 Tage</h3>
            <p>{{ candidate.research.insider_context.summary }}</p>
            <ul v-if="candidate.research.insider_context.top_buyers.length" class="compact-list">
              <li v-for="buyer in candidate.research.insider_context.top_buyers" :key="buyer.name">
                {{ buyer.name }} · {{ buyer.buy_count }} Kauf/Käufe · {{ formatMoney(buyer.total_value) }}
              </li>
            </ul>
          </div>

          <div class="analysis-panel">
            <h3>Upcoming Catalysts</h3>
            <ul v-if="candidate.research.upcoming_catalysts.length" class="research-list">
              <li v-for="catalyst in candidate.research.upcoming_catalysts" :key="`${catalyst.catalyst_type}-${catalyst.evidence}`">
                <strong>{{ catalyst.catalyst_type }} · {{ catalyst.date_text }}</strong>
                <small>{{ catalyst.evidence_quote || catalyst.evidence }}</small>
              </li>
            </ul>
            <p v-else>Kein bevorstehender Katalysator aus den vorhandenen Quellen extrahiert.</p>
            <p class="muted-note">Nur Kontext, kein Score- oder Gate-Signal.</p>
          </div>

          <div class="analysis-panel wide">
            <h3>Event-Timeline</h3>
            <ol v-if="candidate.research.event_timeline.length" class="timeline-list">
              <li v-for="item in candidate.research.event_timeline" :key="`${item.event_date}-${item.title}`">
                <time>{{ item.event_date || '-' }}</time>
                <div>
                  <strong>{{ item.title }}</strong>
                  <small>{{ item.event_type }} · {{ item.source }}</small>
                </div>
              </li>
            </ol>
            <p v-else>Keine chronologische Event-Spur aus News oder 8-Ks verfügbar.</p>
          </div>

          <div class="analysis-panel wide">
            <h3>Risiko-Hinweise</h3>
            <ul v-if="candidate.research.risk_signals.length" class="research-list">
              <li v-for="risk in candidate.research.risk_signals" :key="risk.label">
                <strong>{{ risk.label }}: {{ risk.detail }}</strong>
                <small>Beleg: {{ risk.evidence_quote || risk.evidence }}</small>
              </li>
            </ul>
            <p v-else>Keine erweiterten Risiko-Signale in den verfügbaren Quellen erkannt.</p>
          </div>
        </div>

        <div class="breakdown-grid">
          <div
            v-for="part in candidate.alt_b.score_breakdown"
            :key="part.label"
            class="breakdown-item"
            :class="{ passed: part.passed }"
          >
            <div class="breakdown-head">
              <span>{{ part.label }}</span>
              <strong>{{ part.points }}/{{ part.max_points }}</strong>
            </div>
            <p>{{ part.detail }}</p>
          </div>
        </div>

        <div class="evidence-row">
          <div>
            <span class="evidence-label">News</span>
            <strong>{{ candidate.turnaround_news[0] || 'Kein starkes News-Event' }}</strong>
          </div>
          <div>
            <span class="evidence-label">Belegzitat</span>
            <strong>{{ candidate.alt_b.evidence_quote || candidate.alt_b.event_evidence || '-' }}</strong>
          </div>
          <div>
            <span class="evidence-label">Insider</span>
            <strong>{{ insiderSummary(candidate.insider_buys) }}</strong>
          </div>
          <div>
            <span class="evidence-label">Insider 180 Tage</span>
            <strong>{{ formatMoney(candidate.research.insider_context.total_value) }}</strong>
          </div>
        </div>

        <ol class="decision-log">
          <li v-for="line in candidate.alt_b.decision_log" :key="line">{{ line }}</li>
        </ol>
      </article>
    </section>
  </div>
</template>

<style scoped>
.screener-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.view-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.view-subtitle {
  color: var(--text-secondary);
  font-size: 13px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.score-select {
  width: 132px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.funnel {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
}

.funnel-step {
  min-height: 94px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  padding: 12px;
}

.funnel-count {
  display: block;
  font-size: 22px;
  font-weight: 800;
  color: var(--text-primary);
}

.funnel-label {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}

.funnel-detail {
  display: block;
  margin-top: 5px;
  font-size: 11px;
  color: var(--text-tertiary);
  line-height: 1.35;
}

.candidate-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.candidate-card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 18px;
}

.candidate-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.ticker-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.ticker-row h2 {
  font-size: 21px;
  line-height: 1.1;
}

.candidate-header p {
  margin-top: 5px;
  color: var(--text-secondary);
  font-size: 13px;
}

.score-pill {
  width: 76px;
  height: 56px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 2px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
}

.score-pill strong {
  font-size: 25px;
}

.score-pill span {
  color: var(--text-tertiary);
  font-size: 12px;
}

.score-pill.strong {
  background: var(--green-light);
  border-color: rgba(16,185,129,0.25);
  color: var(--green);
}

.score-pill.watch {
  background: var(--amber-light);
  border-color: rgba(245,158,11,0.25);
  color: var(--amber);
}

.score-pill.muted {
  color: var(--text-tertiary);
}

.candidate-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.candidate-meta span {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 9px;
  color: var(--text-secondary);
  font-size: 12px;
}

.event-strip {
  display: grid;
  grid-template-columns: minmax(150px, 0.8fr) minmax(100px, 0.45fr) minmax(220px, 1.6fr);
  gap: 12px;
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-secondary);
}

.event-strip > div {
  min-width: 0;
}

.event-strip strong {
  display: block;
  color: var(--text-primary);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.analysis-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 16px;
}

.analysis-panel {
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

.analysis-panel.wide {
  grid-column: 1 / -1;
}

.analysis-panel h3,
.breakdown-head span,
.evidence-label {
  font-size: 11px;
  color: var(--text-tertiary);
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.analysis-panel ul {
  margin-top: 8px;
  padding-left: 18px;
  color: var(--text-primary);
  font-size: 13px;
}

.analysis-panel p {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.subhead {
  display: block;
  margin-top: 14px;
}

.research-list,
.compact-list {
  margin-top: 8px;
  padding-left: 18px;
  color: var(--text-primary);
  font-size: 13px;
}

.research-list li + li,
.compact-list li + li {
  margin-top: 8px;
}

.research-list strong {
  display: block;
  font-weight: 650;
  line-height: 1.35;
}

.research-list small,
.timeline-list small,
.muted-note {
  display: block;
  margin-top: 4px;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.timeline-list {
  margin-top: 10px;
  padding-left: 0;
  list-style: none;
}

.timeline-list li {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 12px;
  padding: 9px 0;
  border-top: 1px solid var(--border);
}

.timeline-list li:first-child {
  border-top: none;
}

.timeline-list time {
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 700;
}

.timeline-list strong {
  display: block;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.35;
}

.breakdown-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.breakdown-item {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px;
}

.breakdown-item.passed {
  border-color: rgba(16,185,129,0.28);
  background: var(--green-light);
}

.breakdown-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.breakdown-head strong {
  color: var(--text-primary);
}

.breakdown-item p {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 12px;
}

.evidence-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.evidence-row > div {
  min-width: 0;
}

.evidence-label {
  display: block;
  margin-bottom: 4px;
}

.evidence-row strong {
  display: block;
  color: var(--text-primary);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.decision-log {
  margin-top: 16px;
  padding: 12px 12px 12px 30px;
  background: var(--bg-secondary);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
}

.run-meta {
  margin-top: 4px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.universe-chip {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 5px 10px;
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.progress-box {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  padding: 12px 14px;
  color: var(--text-secondary);
  font-size: 13px;
}

.story-panel {
  margin-top: 16px;
  border: 1px solid rgba(59,130,246,0.25);
  border-radius: var(--radius-sm);
  background: var(--blue-light);
  padding: 12px 14px;
}

.story-panel h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-tertiary);
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.story-panel p {
  margin-top: 8px;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.5;
}

.story-panel blockquote {
  margin-top: 8px;
  padding-left: 10px;
  border-left: 3px solid rgba(59,130,246,0.4);
  color: var(--text-secondary);
  font-size: 12px;
  font-style: italic;
}

.filings-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.filing-chip {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 9px;
  color: var(--blue);
  font-size: 12px;
  text-decoration: none;
}

.filing-chip:hover {
  background: var(--blue-light);
}

.error-box,
.state-box {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-primary);
  padding: 28px;
  text-align: center;
  color: var(--text-secondary);
}

.error-box {
  color: var(--red);
  background: var(--red-light);
}

.empty-state {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-primary);
  padding: 22px;
}

.empty-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.empty-head h2 {
  font-size: 18px;
  line-height: 1.2;
}

.empty-head p {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.refresh-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--blue);
  background: var(--blue-light);
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.empty-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 18px;
}

.empty-grid > div {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px;
  background: var(--bg-secondary);
}

.empty-grid span {
  display: block;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.empty-grid strong {
  display: block;
  margin-top: 5px;
  font-size: 24px;
  line-height: 1;
  color: var(--text-primary);
}

.empty-grid p {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 12px;
}

.empty-reasons {
  margin-top: 16px;
  padding-left: 18px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 980px) {
  .metric-grid,
  .breakdown-grid,
  .empty-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .funnel {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .event-strip,
  .evidence-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .view-toolbar,
  .candidate-header,
  .toolbar-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .score-select,
  .toolbar-actions .btn {
    width: 100%;
  }

  .metric-grid,
  .funnel,
  .event-strip,
  .analysis-grid,
  .breakdown-grid,
  .evidence-row,
  .empty-grid {
    grid-template-columns: 1fr;
  }

  .empty-head {
    flex-direction: column;
  }
}
</style>
