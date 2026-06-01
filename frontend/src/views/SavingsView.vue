<script setup lang="ts">
import { ref, reactive } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { useFormatters } from '@/composables/useFormatters'

const portfolio = usePortfolioStore()
const { fmt, fmtDate } = useFormatters()

const showModal = ref(false)
const form = reactive({ ticker: '', monthly_amount: '', execution_day: '1' })
const saving = ref(false)
const errorMsg = ref('')
const expandedId = ref<number | null>(null)

function nextExecution(day: number): string {
  const now = new Date()
  const d = new Date(now.getFullYear(), now.getMonth(), day)
  if (d <= now) d.setMonth(d.getMonth() + 1)
  return d.toLocaleDateString('de-DE')
}

async function submit() {
  if (!form.ticker || !form.monthly_amount) { errorMsg.value = 'Pflichtfelder ausfüllen'; return }
  saving.value = true
  errorMsg.value = ''
  try {
    await portfolio.addSavingsPlan({
      ticker: form.ticker.toUpperCase(),
      monthly_amount: parseFloat(form.monthly_amount),
      execution_day: parseInt(form.execution_day),
    })
    showModal.value = false
    Object.assign(form, { ticker: '', monthly_amount: '', execution_day: '1' })
  } catch (e: any) {
    errorMsg.value = e.message
  } finally {
    saving.value = false
  }
}

async function execute(id: number) {
  try {
    await portfolio.executeSavingsPlan(id)
  } catch (e: any) {
    alert(e.message)
  }
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px">
      <h1 class="section-title" style="margin: 0">Sparpläne ({{ portfolio.savingsPlans.length }})</h1>
      <button class="btn btn-primary" @click="showModal = true">+ Sparplan erstellen</button>
    </div>

    <div v-if="portfolio.savingsPlans.length === 0" class="card" style="text-align: center; padding: 40px; color: var(--text-tertiary)">
      Noch keine Sparpläne.
    </div>

    <div v-for="plan in portfolio.savingsPlans" :key="plan.id" class="card" style="margin-bottom: 14px">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
        <div>
          <span style="font-size: 16px; font-weight: 700">{{ plan.ticker }}</span>
          <span style="color: var(--text-secondary); margin-left: 10px">$ {{ fmt(plan.monthly_amount) }}/Monat</span>
          <span class="badge badge-blue" style="margin-left: 8px">Am {{ plan.execution_day }}. jeden Monats</span>
        </div>
        <div style="display: flex; gap: 8px; align-items: center">
          <span style="font-size: 13px; color: var(--text-tertiary)">Nächste Ausführung: {{ nextExecution(plan.execution_day) }}</span>
          <button class="btn btn-sm btn-primary" @click="execute(plan.id)">Ausführen</button>
          <button class="btn btn-sm" @click="expandedId = expandedId === plan.id ? null : plan.id">
            Verlauf ({{ plan.history?.length ?? 0 }})
          </button>
          <button class="btn btn-sm btn-danger" @click="portfolio.removeSavingsPlan(plan.id)">✕</button>
        </div>
      </div>

      <div v-if="expandedId === plan.id && plan.history?.length" style="margin-top: 14px; border-top: 1px solid var(--border); padding-top: 12px">
        <table class="table">
          <thead><tr><th>Datum</th><th>Betrag</th><th>Aktien</th><th>Kurs</th></tr></thead>
          <tbody>
            <tr v-for="h in [...plan.history].reverse()" :key="h.id">
              <td>{{ fmtDate(h.date) }}</td>
              <td>$ {{ fmt(h.amount) }}</td>
              <td>{{ h.shares }}</td>
              <td>$ {{ fmt(h.price) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal">
        <h2 class="modal-title">Neuer Sparplan</h2>
        <div class="form-group">
          <label class="form-label">Ticker *</label>
          <input v-model="form.ticker" class="form-input" placeholder="z.B. VOO" style="text-transform: uppercase" />
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">Monatlicher Betrag ($) *</label>
            <input v-model="form.monthly_amount" class="form-input" type="number" step="1" placeholder="100" />
          </div>
          <div class="form-group">
            <label class="form-label">Ausführungstag</label>
            <input v-model="form.execution_day" class="form-input" type="number" min="1" max="28" />
          </div>
        </div>
        <p v-if="errorMsg" style="color: var(--red); font-size: 13px; margin-bottom: 8px">{{ errorMsg }}</p>
        <div class="modal-footer">
          <button class="btn" @click="showModal = false">Abbrechen</button>
          <button class="btn btn-primary" @click="submit" :disabled="saving">
            <span v-if="saving" class="spinner" /> Erstellen
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
