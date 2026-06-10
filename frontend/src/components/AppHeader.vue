<script setup lang="ts">
import { computed } from 'vue'
import { useUiStore, type View } from '@/stores/ui'
import { usePortfolioStore } from '@/stores/portfolio'

const ui = useUiStore()
const portfolio = usePortfolioStore()

const navItems: { id: View; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'positions', label: 'Positionen' },
  { id: 'savings', label: 'Sparpläne' },
  { id: 'news', label: 'News' },
  { id: 'analysis', label: 'KI-Analyse' },
  { id: 'chat', label: 'KI-Chat' },
  { id: 'screener', label: 'Alt B' },
  { id: 'eval', label: 'Eval' },
]
</script>

<template>
  <header class="app-header">
    <div class="header-inner">
      <div class="header-left">
        <button class="hamburger btn btn-sm" @click="ui.sidebarOpen = !ui.sidebarOpen">☰</button>
        <span class="app-title">PortfAIo</span>
        <span v-if="portfolio.loading" class="spinner" style="margin-left: 8px" />
      </div>

      <nav class="desktop-nav">
        <button
          v-for="item in navItems"
          :key="item.id"
          class="nav-btn"
          :class="{ active: ui.activeView === item.id }"
          @click="ui.navigate(item.id)"
        >
          {{ item.label }}
        </button>
      </nav>

      <div class="header-right">
        <button class="btn btn-sm" @click="portfolio.refreshQuotes()" title="Kurse aktualisieren">
          ↻ Aktualisieren
        </button>
        <button class="btn btn-primary btn-sm" @click="ui.openAddModal()">
          + Position
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
}
.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.header-left { display: flex; align-items: center; gap: 10px; }
.app-title { font-size: 18px; font-weight: 800; color: var(--blue); }
.hamburger { display: none; }
.desktop-nav { display: flex; gap: 4px; flex: 1; justify-content: center; }
.nav-btn {
  padding: 6px 14px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s;
}
.nav-btn:hover { background: var(--bg-secondary); color: var(--text-primary); }
.nav-btn.active { background: var(--blue-light); color: var(--blue); font-weight: 600; }
.header-right { display: flex; gap: 8px; align-items: center; }

@media (max-width: 768px) {
  .hamburger { display: inline-flex; }
  .desktop-nav { display: none; }
  .header-right .btn:first-child { display: none; }
}
</style>
