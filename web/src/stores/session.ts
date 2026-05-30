// Pinia store: session — user, departments, active department, active role.
//
// Backend integration notes:
//   * The auth API surface is FLAT: POST /api/login, POST /api/logout,
//     GET /api/me. There is NO /api/auth/me with a body and NO
//     /api/auth/switch-department endpoint.
//   * /api/me returns the SAME shape as POST /api/login (full LoginResponse)
//     so the SPA can re-sync session state without forcing the user to log
//     out and back in. The SPA still keeps a localStorage cache so a page
//     reload renders instantly while /api/me is in-flight, but /api/me is
//     the authoritative source — its response overwrites the cache.
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
    canManageSources(): boolean {
      // Source subscriptions are dept-local data (which feeds we listen to).
      // Same trust level as running crawls or curating topics → analyst+.
      // Wider than canEditDeptConfig, which covers AI config / framework
      // settings (those still require dept_lead).
      if (this.isSuperadmin) return true
      const r = this.activeRole
      return r !== null && roleAtLeast(r, 'analyst')
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
     * Probe /api/me to verify the auth cookie AND fetch the current
     * user + departments fresh from the backend. The response shape is
     * identical to POST /api/login, so we replay it through
     * applyLoginResponse() to populate state and the cache.
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
        // Authoritative path: /api/me returned a fresh LoginResponse.
        const payload = (await res.json()) as LoginPayload
        this.applyLoginResponse(payload)
        return true
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
    },

    /**
     * Force a refresh of the cached session state from the backend.
     *
     * Call this after admin mutations that change the current user's
     * department memberships or role (eg. creating a department, granting
     * a role, removing a member) so the SPA picks up the new state
     * without requiring the user to log out and back in.
     *
     * Thin wrapper around hydrate() — kept as a named action so call
     * sites read intentionally ("refresh the session") rather than as
     * an unexplained re-hydrate.
     */
    async refresh(): Promise<boolean> {
      return this.hydrate()
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
