import { create } from 'zustand'

interface UIState {
  sidebarOpen: boolean
  activeModal: string | null
  toggleSidebar: () => void
  openModal: (id: string) => void
  closeModal: () => void
}

export const useUIStore = create<UIState>()((set) => ({
  sidebarOpen: true,
  activeModal: null,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  openModal: (id) => set({ activeModal: id }),
  closeModal: () => set({ activeModal: null }),
}))
