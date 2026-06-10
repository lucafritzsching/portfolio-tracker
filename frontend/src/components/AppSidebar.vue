<script setup lang="ts">
import { useUiStore, type View } from '@/stores/ui'

const ui = useUiStore()
const navItems: { id: View; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'positions', label: 'Positionen', icon: '📈' },
  { id: 'savings', label: 'Sparpläne', icon: '💰' },
  { id: 'news', label: 'News', icon: '📰' },
  { id: 'analysis', label: 'KI-Analyse', icon: '🤖' },
  { id: 'chat', label: 'KI-Chat', icon: '💬' },
  { id: 'screener', label: 'Alt B Scanner', icon: '🧬' },
  { id: 'eval', label: 'Eval', icon: '🧪' },
]

defineEmits<{ close: [] }>()
</script>

<template>
  <div class="sidebar-overlay" @click="$emit('close')">
    <nav class="sidebar" @click.stop>
      <div class="sidebar-header">
        <span class="sidebar-title">PortfAIo</span>
        <button class="btn btn-sm" @click="$emit('close')">✕</button>
      </div>
      <ul class="sidebar-nav">
        <li v-for="item in navItems" :key="item.id">
          <button
            class="sidebar-item"
            :class="{ active: ui.activeView === item.id }"
            @click="ui.navigate(item.id)"
          >
            <span class="sidebar-icon">{{ item.icon }}</span>
            {{ item.label }}
          </button>
        </li>
      </ul>
    </nav>
  </div>
</template>

<style scoped>
.sidebar-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  z-index: 200;
}
.sidebar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 240px;
  background: var(--bg-primary);
  padding: 0;
  display: flex;
  flex-direction: column;
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.sidebar-title { font-size: 18px; font-weight: 800; color: var(--blue); }
.sidebar-nav { list-style: none; padding: 12px 8px; }
.sidebar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 11px 14px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}
.sidebar-item:hover { background: var(--bg-secondary); color: var(--text-primary); }
.sidebar-item.active { background: var(--blue-light); color: var(--blue); font-weight: 600; }
.sidebar-icon { font-size: 16px; }
</style>
