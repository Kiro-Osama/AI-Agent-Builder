import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  isAuthenticated: boolean
  apiKey: string
  login: (key: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      isAuthenticated: false,
      apiKey: '',
      login: (key: string) => set({ isAuthenticated: true, apiKey: key }),
      logout: () => set({ isAuthenticated: false, apiKey: '' }),
    }),
    {
      name: 'agent-builder-auth',
    },
  ),
)
