import { defineStore } from 'pinia'
import { ref } from 'vue'

export type View = 'dashboard' | 'positions' | 'savings' | 'news' | 'analysis' | 'chat' | 'altb' | 'vergleich' | 'eval'

export const useUiStore = defineStore('ui', () => {
  const activeView = ref<View>('dashboard')
  const sidebarOpen = ref(false)
  const showAddModal = ref(false)
  const editingTicker = ref<string | null>(null)

  function navigate(view: View) {
    activeView.value = view
    sidebarOpen.value = false
  }

  function openAddModal() { showAddModal.value = true }
  function closeAddModal() { showAddModal.value = false }

  function openEditModal(ticker: string) { editingTicker.value = ticker }
  function closeEditModal() { editingTicker.value = null }

  return {
    activeView,
    sidebarOpen,
    showAddModal,
    editingTicker,
    navigate,
    openAddModal,
    closeAddModal,
    openEditModal,
    closeEditModal,
  }
})
