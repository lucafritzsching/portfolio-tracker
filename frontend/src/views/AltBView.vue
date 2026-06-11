<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'
import { useMarkdown } from '@/composables/useMarkdown'

const md = useMarkdown()

const ticker = ref('')
const criterion = ref('hat aktuell eine Turnaround-Story')
const mode = ref<'fast' | 'agentic'>('fast')
const answer = ref('')
const running = ref(false)

function run() {
  const t = ticker.value.trim().toUpperCase()
  const c = criterion.value.trim()
  if (!t || !c || running.value) return
  running.value = true
  answer.value = ''
  const source = api.agent.nlTarget(c, t, mode.value)
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
</script>

<template>
  <div>
    <h2 class="section-title">Alt B — NL-Ziel-Agent</h2>
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
          @keydown.enter="run"
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
        placeholder="Freitext-Kriterium, z. B. „hat aktuell eine Turnaround-Story""
        :disabled="running"
        style="width: 100%; padding: 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 14px; resize: vertical"
        @keydown.ctrl.enter="run"
      />
      <div style="margin-top: 10px; display: flex; justify-content: flex-end">
        <button class="btn btn-primary" :disabled="running || !ticker.trim() || !criterion.trim()" @click="run">
          <span v-if="running" class="spinner" />
          {{ running ? 'Beurteilt…' : 'Beurteilen' }}
        </button>
      </div>
    </div>

    <div v-if="answer" class="card ai-box markdown" v-html="md.render(answer)"></div>
  </div>
</template>

<style scoped>
.markdown { white-space: normal; }
.markdown :deep(h3) { font-size: 15px; font-weight: 800; margin: 14px 0 6px; }
.markdown :deep(h4) { font-size: 14px; font-weight: 700; margin: 10px 0 4px; }
.markdown :deep(p) { margin: 6px 0; }
.markdown :deep(ul) { margin: 6px 0; padding-left: 18px; }
.markdown :deep(strong) { font-weight: 700; }
</style>
