<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'

// Chart.js is loaded from CDN in index.html
declare const Chart: any

const portfolio = usePortfolioStore()
const allocCanvas = ref<HTMLCanvasElement | null>(null)
const sectorCanvas = ref<HTMLCanvasElement | null>(null)
let allocChart: any = null
let sectorChart: any = null

const COLORS = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6','#6366f1','#a78bfa']

function renderCharts() {
  const positions = portfolio.positions
  if (!positions.length || !allocCanvas.value || !sectorCanvas.value) return

  const totalValue = portfolio.stats.total_value
  if (totalValue === 0) return

  // Allocation chart
  const allocLabels = positions.map(p => p.ticker)
  const allocData = positions.map(p => ((p.current_price ?? 0) * p.shares))

  if (allocChart) allocChart.destroy()
  allocChart = new Chart(allocCanvas.value, {
    type: 'doughnut',
    data: {
      labels: allocLabels,
      datasets: [{ data: allocData, backgroundColor: COLORS, borderWidth: 2, borderColor: 'transparent' }],
    },
    options: {
      plugins: { legend: { display: false }, tooltip: {
        callbacks: {
          label: (ctx: any) => {
            const pct = (ctx.raw / totalValue * 100).toFixed(1)
            return ` ${ctx.label}: €${ctx.raw.toFixed(0)} (${pct}%)`
          }
        }
      }},
      cutout: '65%',
    },
  })

  // Sector chart
  const sectorMap: Record<string, number> = {}
  for (const pos of positions) {
    const v = (pos.current_price ?? 0) * pos.shares
    sectorMap[pos.sector] = (sectorMap[pos.sector] || 0) + v
  }

  if (sectorChart) sectorChart.destroy()
  sectorChart = new Chart(sectorCanvas.value, {
    type: 'doughnut',
    data: {
      labels: Object.keys(sectorMap),
      datasets: [{ data: Object.values(sectorMap), backgroundColor: COLORS, borderWidth: 2, borderColor: 'transparent' }],
    },
    options: {
      plugins: { legend: { position: 'bottom', labels: { font: { size: 11 } } } },
      cutout: '60%',
    },
  })
}

onMounted(renderCharts)
watch(() => portfolio.positions, renderCharts, { deep: true })
onUnmounted(() => {
  allocChart?.destroy()
  sectorChart?.destroy()
})
</script>

<template>
  <div class="card">
    <h3 class="section-title">Allokation</h3>
    <canvas ref="allocCanvas" height="200" />
  </div>
  <div class="card">
    <h3 class="section-title">Sektoren</h3>
    <canvas ref="sectorCanvas" height="200" />
  </div>
</template>
