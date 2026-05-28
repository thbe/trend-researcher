// Pinia store: frameworks — system catalog + active dept's enabled set.
//
// Endpoints (per services/api/src/api/routes/frameworks.py):
//   GET  /api/frameworks         -> FrameworksListResponse (all rows)
//   GET  /api/frameworks/mine    -> DepartmentFrameworksListResponse
//                                   (rows enabled for active dept + is_default)
//   PUT  /api/frameworks/mine    -> body DepartmentFrameworksUpdate
//                                   (replaces enabled set; sets default)
//
// `mine` is keyed off the X-Active-Department header injected by
// api/client.ts, so calling `loadMine()` after `session.switchDepartment`
// refreshes the per-dept enabled list naturally.

import { defineStore } from 'pinia'

import { request, ApiError } from '@/api/client'

export interface Framework {
  id: string
  key: string
  name: string
  description: string | null
  display_component: string
  prompt_version: string
}

export interface DepartmentFramework extends Framework {
  is_default: boolean
}

interface FrameworksListResponse {
  frameworks: Framework[]
  total: number
}

interface DepartmentFrameworksListResponse {
  frameworks: DepartmentFramework[]
  total: number
}

export interface DepartmentFrameworksUpdate {
  enabled: string[]
  default: string
}

interface FrameworksState {
  system: Framework[]
  mine: DepartmentFramework[]
  defaultId: string | null
  loadedSystem: boolean
  loadedMineForDept: string | null
  loading: boolean
  error: string | null
}

export const useFrameworksStore = defineStore('frameworks', {
  state: (): FrameworksState => ({
    system: [],
    mine: [],
    defaultId: null,
    loadedSystem: false,
    loadedMineForDept: null,
    loading: false,
    error: null,
  }),

  getters: {
    /** O(1)-ish lookup; small N (≤ ~10 frameworks) makes the array fine. */
    byId(state) {
      return (id: string): Framework | undefined =>
        state.system.find((f) => f.id === id) ??
        state.mine.find((f) => f.id === id)
    },
    defaultFramework(state): DepartmentFramework | null {
      if (!state.defaultId) return null
      return state.mine.find((f) => f.id === state.defaultId) ?? null
    },
    displayComponentFor() {
      return (id: string | null | undefined): string | null => {
        if (!id) return null
        return this.byId(id)?.display_component ?? null
      }
    },
  },

  actions: {
    async loadSystem(force = false): Promise<void> {
      if (this.loadedSystem && !force) return
      this.loading = true
      this.error = null
      try {
        const body = await request<FrameworksListResponse>('/api/frameworks')
        this.system = body.frameworks
        this.loadedSystem = true
      } catch (err) {
        this.error = err instanceof Error ? err.message : 'Failed to load frameworks.'
        throw err
      } finally {
        this.loading = false
      }
    },

    async loadMine(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const body = await request<DepartmentFrameworksListResponse>(
          '/api/frameworks/mine',
        )
        this.mine = body.frameworks
        this.defaultId = body.frameworks.find((f) => f.is_default)?.id ?? null
        // Read active dept off the localStorage key shared with session — we
        // don't import the session store to keep the dep graph one-way.
        this.loadedMineForDept =
          typeof localStorage !== 'undefined'
            ? localStorage.getItem('activeDepartment')
            : null
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          // Pre-auth or missing dept membership — clear silently; UI handles redirect.
          this.mine = []
          this.defaultId = null
          this.loadedMineForDept = null
        } else {
          this.error = err instanceof Error ? err.message : 'Failed to load dept frameworks.'
          throw err
        }
      } finally {
        this.loading = false
      }
    },

    async updateMine(payload: DepartmentFrameworksUpdate): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const body = await request<DepartmentFrameworksListResponse>(
          '/api/frameworks/mine',
          { method: 'PUT', body: payload },
        )
        this.mine = body.frameworks
        this.defaultId = body.frameworks.find((f) => f.is_default)?.id ?? null
      } catch (err) {
        this.error = err instanceof Error ? err.message : 'Failed to save dept frameworks.'
        throw err
      } finally {
        this.loading = false
      }
    },

    /** Clear all per-dept state (called on logout). System catalog kept. */
    clearMine(): void {
      this.mine = []
      this.defaultId = null
      this.loadedMineForDept = null
    },
  },
})
