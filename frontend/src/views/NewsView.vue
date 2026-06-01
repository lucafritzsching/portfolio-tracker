<script setup lang="ts">
import { ref } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { api } from '@/api/client'
import { useFormatters } from '@/composables/useFormatters'
import type { NewsItem } from '@/types'

const portfolio = usePortfolioStore()
const { fmtDate } = useFormatters()

const news = ref<NewsItem[]>([])
const loading = ref(false)
const selectedTicker = ref<string | null>(null)

async function loadNews(ticker: string) {
  selectedTicker.value = ticker
  loading.value = true
  try {
    news.value = await api.marketData.news(ticker, 14)
  } catch (e: any) {
    news.value = []
  } finally {
    loading.value = false
  }
}

function sentimentLabel(s: number | null): string {
  if (s == null) return ''
  if (s > 0.1) return 'positiv'
  if (s < -0.1) return 'negativ'
  return 'neutral'
}

function sentimentClass(s: number | null): string {
  if (s == null) return ''
  if (s > 0.1) return 'positive'
  if (s < -0.1) return 'negative'
  return 'neutral'
}
</script>

<template>
  <div>
    <h1 class="section-title">News & Nachrichten</h1>
    <p style="color: var(--text-secondary); margin-bottom: 20px; font-size: 13px">
      Wähle eine Position um aktuelle Nachrichten zu laden (gecacht via Finnhub News API).
    </p>

    <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px">
      <button
        v-for="pos in portfolio.positions"
        :key="pos.ticker"
        class="btn"
        :class="{ 'btn-primary': selectedTicker === pos.ticker }"
        @click="loadNews(pos.ticker)"
      >
        {{ pos.ticker }}
      </button>
    </div>

    <div v-if="loading" style="text-align: center; padding: 40px; color: var(--text-tertiary)">
      <span class="spinner" /> News werden geladen...
    </div>

    <div v-else-if="news.length === 0 && selectedTicker" class="card" style="text-align: center; padding: 30px; color: var(--text-tertiary)">
      Keine News für {{ selectedTicker }} gefunden. (Finnhub News-Cache leer – Finnhub-API-Key prüfen)
    </div>

    <div v-for="item in news" :key="item.id" class="card" style="margin-bottom: 12px">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px">
        <div style="flex: 1">
          <a v-if="item.url" :href="item.url" target="_blank" rel="noopener" style="font-weight: 600; font-size: 14px; color: var(--blue); text-decoration: none">
            {{ item.headline }}
          </a>
          <span v-else style="font-weight: 600; font-size: 14px">{{ item.headline }}</span>
          <p v-if="item.summary" style="color: var(--text-secondary); font-size: 13px; margin-top: 6px">{{ item.summary }}</p>
        </div>
        <div style="text-align: right; flex-shrink: 0">
          <div style="font-size: 12px; color: var(--text-tertiary)">{{ fmtDate(item.published_at) }}</div>
          <div v-if="item.source" style="font-size: 11px; color: var(--text-tertiary)">{{ item.source }}</div>
          <div v-if="item.sentiment != null" :class="sentimentClass(item.sentiment)" style="font-size: 11px; font-weight: 600; margin-top: 2px">
            {{ sentimentLabel(item.sentiment) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
