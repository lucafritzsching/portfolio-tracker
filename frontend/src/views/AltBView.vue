<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'
import { useMarkdown } from '@/composables/useMarkdown'

const md = useMarkdown()

const feature = ref<'finder' | 'single'>('finder')
const mode = ref<'fast' | 'agentic'>('fast')
const answer = ref('')
const running = ref(false)

// Single-ticker NL-target
const ticker = ref('')
const criterion = ref('hat aktuell eine Turnaround-Story')

// Strategy finder
const mandate = ref('Nasdaq Biotech, < 15 Mrd. Market Cap, > 20% Umsatzwachstum, aktuelle Turnaround-Story')
const maxCandidates = ref(8)

function stream(source: EventSource) {
  running.value = true
  answer.value = ''
  source.onmessage = (e) => {
    if (e.data === '[DONE]') {
      running.value = false
      source.close()
      return
    }
    answer.value += e.data.replace(/\\n/g, '\n')
  }
  source.onerror = () => {
    running.value = false
    source.close()
    if (!answer.value) answer.value = '[Verbindungsfehler zum Agenten]'
  }
}

function runSingle() {
  const t = ticker.value.trim().toUpperCase()
  const c = criterion.value.trim()
  if (!t || !c || running.value) return
  stream(api.agent.nlTarget(c, t, mode.value))
}

function runFinder() {
  const m = mandate.value.trim()
  if (!m || running.value) return
  stream(api.agent.finder(m, mode.value, maxCandidates.value))
}
</script>

<template>
  <div>
    <h2 class="section-title">Alt B — NL-Ziel-Agent</h2>

    <div class="tabs">
      <button :class="['tab', feature === 'finder' && 'active']" :disabled="running" @click="feature = 'finder'">
        Strategie-Finder
      </button>
      <button :class="['tab', feature === 'single' && 'active']" :disabled="running" @click="feature = 'single'">
        Einzel-Ticker
      </button>
    </div>

    <!-- Strategy finder: free-text mandate → screen → NL-Agent on survivors -->
    <div v-if="feature === 'finder'">
      <p style="color: var(--text-secondary); font-size: 13px; margin-bottom: 16px">
        Findet <strong>Unternehmen zu einer Freitext-Strategie</strong>: harte Filter (Börse/Sektor/Market
        Cap/Wachstum) laufen als deterministischer Screen, das LLM beurteilt nur das qualitative
        NL-Kriterium der Überlebenden. Mit nachvollziehbarem Parse + Funnel + Clamp-Trace.
      </p>

      <div class="card" style="margin-bottom: 16px">
        <textarea
          v-model="mandate"
          rows="2"
          placeholder="Mandat, z. B. „Nasdaq Biotech, <15 Mrd., >20% Wachstum, Turnaround-Story“"
          :disabled="running"
          style="width: 100%; padding: 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 14px; resize: vertical"
          @keydown.ctrl.enter="runFinder"
        />
        <div style="margin-top: 10px; display: flex; gap: 14px; align-items: center; flex-wrap: wrap">
          <label style="display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary)">
            Modus:
            <select v-model="mode" :disabled="running" style="padding: 8px; border-radius: 6px; border: 1px solid var(--border)">
              <option value="fast">fast (1 LLM-Call/Kandidat)</option>
              <option value="agentic">agentic (Tool-Loop)</option>
            </select>
          </label>
          <label style="display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary)">
            Max. Kandidaten:
            <input
              v-model.number="maxCandidates"
              type="number"
              min="1"
              max="15"
              :disabled="running"
              style="width: 64px; padding: 8px; border-radius: 6px; border: 1px solid var(--border)"
            />
          </label>
          <button class="btn btn-primary" style="margin-left: auto" :disabled="running || !mandate.trim()" @click="runFinder">
            <span v-if="running" class="spinner" />
            {{ running ? 'Sucht…' : 'Unternehmen finden' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Single ticker: judge one named ticker against a free-text criterion -->
    <div v-else>
      <p style="color: var(--text-secondary); font-size: 13px; margin-bottom: 16px">
        Prüft ein <strong>Freitext-Kriterium</strong> gegen die aktuellen News einer Aktie: erfüllt der Titel
        das Kriterium gerade? Mit nachvollziehbarem Trace (deterministische Regex-Basis vs. LLM-Urteil).
      </p>

      <div class="card" style="margin-bottom: 16px">
        <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px">
          <input
            v-model="ticker"
            placeholder="Ticker, z. B. AAPL"
            :disabled="running"
            style="flex: 0 0 160px; padding: 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 14px"
            @keydown.enter="runSingle"
          />
          <label style="display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary)">
            Modus:
            <select v-model="mode" :disabled="running" style="padding: 8px; border-radius: 6px; border: 1px solid var(--border)">
              <option value="fast">fast (1 LLM-Call)</option>
              <option value="agentic">agentic (Tool-Loop)</option>
            </select>
          </label>
        </div>
        <textarea
          v-model="criterion"
          rows="2"
          placeholder="Freitext-Kriterium, z. B. „hat aktuell eine Turnaround-Story“"
          :disabled="running"
          style="width: 100%; padding: 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 14px; resize: vertical"
          @keydown.ctrl.enter="runSingle"
        />
        <div style="margin-top: 10px; display: flex; justify-content: flex-end">
          <button class="btn btn-primary" :disabled="running || !ticker.trim() || !criterion.trim()" @click="runSingle">
            <span v-if="running" class="spinner" />
            {{ running ? 'Beurteilt…' : 'Beurteilen' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="answer" class="card ai-box markdown" v-html="md.render(answer)"></div>
  </div>
</template>

<style scoped>
.tabs { display: flex; gap: 6px; margin-bottom: 16px; }
.tab {
  padding: 8px 16px; border-radius: 6px; border: 1px solid var(--border);
  background: var(--bg); color: var(--text-secondary); font-size: 13px; cursor: pointer;
}
.tab.active { background: var(--primary, #3367d6); color: #fff; border-color: var(--primary, #3367d6); }
.tab:disabled { opacity: 0.6; cursor: default; }
.markdown { white-space: normal; }
.markdown :deep(h3) { font-size: 15px; font-weight: 800; margin: 14px 0 6px; }
.markdown :deep(h4) { font-size: 14px; font-weight: 700; margin: 10px 0 4px; }
.markdown :deep(p) { margin: 6px 0; }
.markdown :deep(ul) { margin: 6px 0; padding-left: 18px; }
.markdown :deep(strong) { font-weight: 700; }
</style>
