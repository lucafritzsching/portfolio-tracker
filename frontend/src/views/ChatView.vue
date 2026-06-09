<script setup lang="ts">
import { ref } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { api } from '@/api/client'
import { useMarkdown } from '@/composables/useMarkdown'

const portfolio = usePortfolioStore()
const md = useMarkdown()

const question = ref('')
const answer = ref('')
const running = ref(false)
const history = ref<{ q: string; a: string }[]>([])

function ask() {
  const q = question.value.trim()
  if (!q || running.value) return
  running.value = true
  answer.value = ''
  const source = api.agent.chat(q, portfolio.currentPrices)
  source.onmessage = (e) => {
    if (e.data === '[DONE]') {
      running.value = false
      source.close()
      if (answer.value) history.value.unshift({ q, a: answer.value })
      question.value = ''
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
    <h2 class="section-title">KI-Chat</h2>
    <p style="color: var(--text-secondary); font-size: 13px; margin-bottom: 16px">
      Freitext-Fragen zum Portfolio. Der Agent nutzt Tools für Live-Daten (auch Ticker außerhalb des Depots).
    </p>

    <div class="card" style="margin-bottom: 16px">
      <textarea
        v-model="question"
        rows="3"
        placeholder="z. B. „Ich habe 5000 €, mittleres Risiko — womit diversifizieren?“"
        style="width: 100%; padding: 10px; border-radius: 6px; border: 1px solid var(--border); font-size: 14px; resize: vertical"
        :disabled="running"
        @keydown.ctrl.enter="ask"
      />
      <div style="margin-top: 10px; display: flex; justify-content: flex-end">
        <button class="btn btn-primary" :disabled="running || !question.trim()" @click="ask">
          <span v-if="running" class="spinner" />
          {{ running ? 'Antwortet…' : 'Fragen' }}
        </button>
      </div>
    </div>

    <div v-if="answer" class="card ai-box markdown" v-html="md.render(answer)"></div>

    <div v-if="history.length > 1 || (history.length === 1 && !answer)" style="margin-top: 24px">
      <h3 class="section-title" style="font-size: 14px">Verlauf</h3>
      <div v-for="(h, i) in history.slice(answer ? 1 : 0)" :key="i" class="card" style="margin-bottom: 12px">
        <div style="font-weight: 600; font-size: 13px; margin-bottom: 8px">Frage: {{ h.q }}</div>
        <div class="markdown" v-html="md.render(h.a)"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.markdown { white-space: normal; }
.markdown :deep(h3) { font-size: 15px; font-weight: 800; margin: 12px 0 6px; }
.markdown :deep(p) { margin: 6px 0; }
.markdown :deep(ul) { margin: 6px 0; padding-left: 18px; }
</style>
