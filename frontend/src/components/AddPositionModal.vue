<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useUiStore } from '@/stores/ui'
import { usePortfolioStore } from '@/stores/portfolio'
import { api } from '@/api/client'

const ui = useUiStore()
const portfolio = usePortfolioStore()

const form = reactive({
  ticker: '',
  name: '',
  sector: 'Technologie',
  shares: '',
  buyPrice: '',
})
const quoteLoading = ref(false)
const quoteError = ref('')
const saving = ref(false)
const errorMsg = ref('')

const sectors = ['Technologie', 'Finanzen', 'Gesundheit', 'Energie', 'Konsumgüter', 'Industrie', 'ETF / Fonds', 'Sonstiges']

async function lookupTicker() {
  if (!form.ticker.trim()) return
  quoteLoading.value = true
  quoteError.value = ''
  try {
    const q = await api.quotes.get(form.ticker.trim().toUpperCase())
    if (!form.name) form.name = q.ticker
    form.ticker = q.ticker
  } catch {
    quoteError.value = 'Symbol nicht gefunden'
  } finally {
    quoteLoading.value = false
  }
}

async function submit() {
  if (!form.ticker || !form.name) { errorMsg.value = 'Ticker und Name sind Pflichtfelder.'; return }
  saving.value = true
  errorMsg.value = ''
  try {
    await portfolio.addPosition({
      ticker: form.ticker.toUpperCase(),
      name: form.name,
      sector: form.sector,
      shares: form.shares ? parseFloat(form.shares) : undefined,
      buyPrice: form.buyPrice ? parseFloat(form.buyPrice) : undefined,
    })
    ui.closeAddModal()
  } catch (e: any) {
    errorMsg.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="ui.closeAddModal()">
    <div class="modal">
      <h2 class="modal-title">Position hinzufügen</h2>

      <div class="form-group">
        <label class="form-label">Ticker-Symbol *</label>
        <div style="display: flex; gap: 8px">
          <input
            v-model="form.ticker"
            class="form-input"
            placeholder="z.B. AAPL"
            @keyup.enter="lookupTicker"
            style="flex: 1; text-transform: uppercase"
          />
          <button class="btn btn-sm" @click="lookupTicker" :disabled="quoteLoading">
            <span v-if="quoteLoading" class="spinner" />
            <span v-else>Suchen</span>
          </button>
        </div>
        <p v-if="quoteError" style="color: var(--red); font-size: 12px; margin-top: 4px">{{ quoteError }}</p>
      </div>

      <div class="form-group">
        <label class="form-label">Name *</label>
        <input v-model="form.name" class="form-input" placeholder="z.B. Apple Inc." />
      </div>

      <div class="form-group">
        <label class="form-label">Sektor</label>
        <select v-model="form.sector" class="form-input">
          <option v-for="s in sectors" :key="s" :value="s">{{ s }}</option>
        </select>
      </div>

      <div class="grid-2">
        <div class="form-group">
          <label class="form-label">Anzahl Aktien</label>
          <input v-model="form.shares" class="form-input" type="number" step="0.0001" placeholder="0" />
        </div>
        <div class="form-group">
          <label class="form-label">Kaufkurs (€)</label>
          <input v-model="form.buyPrice" class="form-input" type="number" step="0.01" placeholder="0.00" />
        </div>
      </div>

      <p v-if="errorMsg" style="color: var(--red); font-size: 13px; margin-bottom: 8px">{{ errorMsg }}</p>

      <div class="modal-footer">
        <button class="btn" @click="ui.closeAddModal()">Abbrechen</button>
        <button class="btn btn-primary" @click="submit" :disabled="saving">
          <span v-if="saving" class="spinner" />
          <span v-else>Hinzufügen</span>
        </button>
      </div>
    </div>
  </div>
</template>
