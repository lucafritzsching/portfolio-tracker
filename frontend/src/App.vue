<script setup lang="ts">
import { onMounted } from 'vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { useUiStore } from '@/stores/ui'
import AppHeader from '@/components/AppHeader.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import AddPositionModal from '@/components/AddPositionModal.vue'
import DashboardView from '@/views/DashboardView.vue'
import PositionsView from '@/views/PositionsView.vue'
import SavingsView from '@/views/SavingsView.vue'
import NewsView from '@/views/NewsView.vue'
import ChatView from '@/views/ChatView.vue'
import EvalView from '@/views/EvalView.vue'

const portfolio = usePortfolioStore()
const ui = useUiStore()

onMounted(async () => {
  await portfolio.loadPositions()
  await portfolio.refreshQuotes()
  await portfolio.loadSavingsPlans()
})
</script>

<template>
  <div class="app-layout">
    <AppHeader />
    <AppSidebar v-if="ui.sidebarOpen" @close="ui.sidebarOpen = false" />

    <main class="app-main">
      <!-- KeepAlive caches the views so the KI-Agent keeps streaming + preserves its answer/trace
           when you switch tabs mid-run (and come back). -->
      <KeepAlive>
        <DashboardView v-if="ui.activeView === 'dashboard'" />
        <PositionsView v-else-if="ui.activeView === 'positions'" />
        <SavingsView v-else-if="ui.activeView === 'savings'" />
        <NewsView v-else-if="ui.activeView === 'news'" />
        <ChatView v-else-if="ui.activeView === 'chat'" />
        <EvalView v-else-if="ui.activeView === 'eval'" />
      </KeepAlive>
    </main>

    <AddPositionModal v-if="ui.showAddModal" />
  </div>
</template>

<style>
@import '@/assets/main.css';

.app-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-main {
  flex: 1;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  padding: 24px 20px;
}

@media (max-width: 768px) {
  .app-main { padding: 16px 12px; }
}
</style>
