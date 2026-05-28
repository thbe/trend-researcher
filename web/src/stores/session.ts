// Pinia store: session — user, departments, active department, active role.
//
// Backend integration notes (adapted from plan vs reality discoveries):
//   * The auth API surface is FLAT: POST /api/login, POST /api/logout,
//     GET /api/me. There is NO /api/auth/me with a body and NO
//     /api/auth/switch-department endpoint.
//   * /api/me returns ONLY {ok: true} once the cookie is validated. It
//     does NOT echo back user / departments. Therefore the SPA caches the
//     full LoginResponse to localStorage['session'] at login time and
//     rehydrates from that cache after a page reload, using GET /api/me
//     purely as a cookie liveness probe.
//   * Switching departments is PURE client-side state: update Pinia +
//     localStorage. Every subsequent API call carries the new value via
//     the X-Active-Department header injected by api/client.ts.

import { defineStore } from 'pinia'

import type { Role } from '@/lib/roles'
import { roleAtLeast } from '@/lib/roles'

export interface SessionDepartment {
  id: string
  name: string
  slug: string
  role: Role
}

export interface SessionUser {
  username: string
  is_superadmin: boolean
}

export interface LoginPayload {
  ok: boolean
  username: string
  is_superadmin: boolean
  departments: SessionDepartment[]
}

interface CachedSession {
  user: SessionUser
  departments: SessionDepartment[]
}

const STORAGE_KEY_SESSION = 'session'
const STORAGE_KEY_ACTIVE_DEPT = 'activeDepartment'

function readCachedSession(): CachedSession | null {
  if (typeof localStorage === 'undefined') return null
  const raw = localStorage.getItem(STORAGE_KEY_SESSION)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as CachedSession
    if (!parsed?.user?.username || !Array.isArray(parsed.departments)) return null
    return parsed
  } catch {
    return null
  }
}

function writeCachedSession(value: CachedSession | null): void {
  if (typeof localStorage === 'undefined') return
  if (value === null) {
    localStorage.removeItem(STORAGE_KEY_SESSION)
  } else {
    localStorage.setItem(STORAGE_KEY_SESSION, JSON.stringify(value))
  }
}

function readActiveDept(): string | null {
  if (typeof localStorage === 'undefined') return null
  return localStorage.getItem(STORAGE_KEY_ACTIVE_DEPT)
}

function writeActiveDept(id: string | null): void {
  if (typeof localStorage === 'undefined') return
  if (id === null) {
    localStorage.removeItem(STORAGE_KEY_ACTIVE_DEPT)
  } else {
    localStorage.setItem(STORAGE_KEY_ACTIVE_DEPT, id)
  }
}

interface SessionState {
  user: SessionUser | null
  departments: SessionDepartment[]
  activeDepartmentId: string | null
  hydrated: boolean
}

export const useSessionStore = defineStore('session', {
  state: (): SessionState => ({
    user: null,
    departments: [],
    activeDepartmentId: null,
    hydrated: false,
  }),

  getters: {
    isAuthenticated: (s) => s.user !== null,
    isSuperadmin: (s) => s.user?.is_superadmin === true,
    activeDepartment: (s): SessionDepartment | null =>
      s.departments.find((d) => d.id === s.activeDepartmentId) ?? null,
    activeRole(): Role | null {
      return this.activeDepartment?.role ?? null
    },
    // RBAC getters. Superadmin overrides every dept-scoped permission.
    canAssess(): boolean {
      if (this.isSuperadmin) return true
      const r = this.activeRole
      return r !== null && roleAtLeast(r, 'analyst')
    },
    canEditDeptConfig(): boolean {
      if (this.isSuperadmin) return true
      const r = this.activeRole
      return r !== null && roleAtLeast(r, 'dept_lead')
    },
    canHarmonize(): boolean {
      return this.canEditDeptConfig
    },
    canManageMembers(): boolean {
      return this.canEditDeptConfig
    },
    canManageDepartments(): boolean {
      return this.isSuperadmin
    },
  },

  actions: {
    /**
     * Populate state from the LoginResponse and persist a cache so a page
     * reload can rehydrate without a follow-up roundtrip.
     */
    applyLoginResponse(payload: LoginPayload): void {
      this.user = { username: payload.username, is_superadmin: payload.is_superadmin }
      this.departments = [...payload.departments]
      // Pick the persisted active dept if it's still a member; otherwise the
      // first dept; otherwise null (superadmin with zero memberships is a
      // valid but rare state — backend returns all depts so this is usually
      // safe).
      const persisted = readActiveDept()
      const persistedValid = persisted && this.departments.some((d) => d.id === persisted)
      const next = persistedValid ? persisted : this.departments[0]?.id ?? null
      this.activeDepartmentId = next
      writeActiveDept(next)
      writeCachedSession({ user: this.user, departments: this.departments })
      this.hydrated = true
    },

    /**
     * Probe /api/me to verify the auth cookie, then rehydrate user +
     * departments from the localStorage cache written at login time.
     *
     * Returns true if the session is usable; false if the user must log in.
     * Never throws on auth failure — callers (router guard, app mount)
     * decide whether to redirect.
     */
    async hydrate(): Promise<boolean> {
      try {
        const res = await fetch('/api/me', {
          method: 'GET',
          headers: { Accept: 'application/json' },
        })
        if (res.status === 401) {
          this.clear()
          return false
        }
        if (!res.ok) {
          // Network or 5xx — keep any cached state we have but flag unhydrated.
          this.hydrated = false
          return this.user !== null
        }
      } catch {
        // Network failure: optimistically keep cached state so an offline
        // SPA reload doesn't immediately bounce to /login.
        const cached = readCachedSession()
        if (cached) {
          this.user = cached.user
          this.departments = cached.departments
          const persisted = readActiveDept()
          const persistedValid =
            persisted && this.departments.some((d) => d.id === persisted)
          this.activeDepartmentId = persistedValid
            ? persisted
            : this.departments[0]?.id ?? null
        }
        this.hydrated = false
        return this.user !== null
      }

      // /api/me said the cookie is good. Replay the cache.
      const cached = readCachedSession()
      if (!cached) {
        // Cookie valid but no cache (eg. user cleared storage). Force
        // re-login so the SPA can capture the LoginResponse again.
        this.clear()
        return false
      }
      this.user = cached.user
      this.departments = cached.departments
      const persisted = readActiveDept()
      const persistedValid =
        persisted && this.departments.some((d) => d.id === persisted)
      this.activeDepartmentId = persistedValid
        ? persisted
        : this.departments[0]?.id ?? null
      writeActiveDept(this.activeDepartmentId)
      this.hydrated = true
      return true
    },

    /**
     * Switch the active department. Pure client-side: update state +
     * localStorage; trigger frameworks reload so per-dept enabled set is
     * fresh on the next render.
     */
    async switchDepartment(id: string): Promise<void> {
      if (!this.departments.some((d) => d.id === id)) {
        throw new Error(`Department ${id} is not in current session.`)
      }
      this.activeDepartmentId = id
      writeActiveDept(id)
      // Dynamic import to avoid circular dependency at module-load time:
      // frameworks store may import session (it does not today, but this
      // keeps the dep direction safe for future edits).
      const { useFrameworksStore } = await import('@/stores/frameworks')
      await useFrameworksStore().loadMine()
    },

    /**
     * Best-effort logout: tell the API to invalidate the cookie, then clear
     * all client state regardless of the network outcome.
     */
    async logout(): Promise<void> {
      try {
        await fetch('/api/logout', {
          method: 'POST',
          headers: { Accept: 'application/json' },
        })
      } catch {
        // ignore — we clear local state regardless.
      }
      this.clear()
    },

    /** Wipe in-memory + persisted state. Does not touch the router. */
    clear(): void {
      this.user = null
      this.departments = []
      this.activeDepartmentId = null
      this.hydrated = false
      writeCachedSession(null)
      writeActiveDept(null)
    },
  },
})
