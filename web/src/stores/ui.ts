// Pinia store: ui — lightweight global UI signals (currently a single
// snackbar for cross-view feedback such as auth/RBAC denials from the
// router guard). Kept intentionally small; views with view-local alerts
// should continue using their own state.
import { defineStore } from 'pinia'

export type SnackbarColor = 'success' | 'info' | 'warning' | 'error'

interface SnackbarMessage {
  text: string
  color: SnackbarColor
  timeout: number
}

interface UiState {
  snackbar: SnackbarMessage | null
}

export const useUiStore = defineStore('ui', {
  state: (): UiState => ({
    snackbar: null,
  }),
  actions: {
    notify(text: string, color: SnackbarColor = 'info', timeout = 4000): void {
      this.snackbar = { text, color, timeout }
    },
    error(text: string, timeout = 5000): void {
      this.notify(text, 'error', timeout)
    },
    clear(): void {
      this.snackbar = null
    },
  },
})
