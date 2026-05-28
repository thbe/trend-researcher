// Tests for the session store — the SPA's auth + RBAC linchpin.
// Covers the three trickiest behaviours from CONTEXT discoveries:
//   1. applyLoginResponse — caches user + departments and picks an
//      active department (persisted-if-valid, else first).
//   2. hydrate() — replays cache after /api/me liveness probe, and
//      forces re-login when the cache is missing.
//   3. switchDepartment / RBAC getters — superadmin override and the
//      analyst / dept_lead ordinal gates.

import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { useSessionStore, type LoginPayload } from '@/stores/session'

// Mock the frameworks store import that switchDepartment triggers via
// dynamic import. We don't want a real HTTP call from a unit test.
vi.mock('@/stores/frameworks', () => ({
  useFrameworksStore: () => ({
    loadMine: vi.fn().mockResolvedValue(undefined),
  }),
}))

const DEPT_A = {
  id: '00000000-0000-0000-0000-0000000000a1',
  name: 'Alpha',
  slug: 'alpha',
  role: 'analyst' as const,
}
const DEPT_B = {
  id: '00000000-0000-0000-0000-0000000000b2',
  name: 'Bravo',
  slug: 'bravo',
  role: 'dept_lead' as const,
}
const DEPT_C_VIEWER = {
  id: '00000000-0000-0000-0000-0000000000c3',
  name: 'Charlie',
  slug: 'charlie',
  role: 'viewer' as const,
}

function loginPayload(overrides: Partial<LoginPayload> = {}): LoginPayload {
  return {
    ok: true,
    username: 'tester',
    is_superadmin: false,
    departments: [DEPT_A, DEPT_B],
    ...overrides,
  }
}

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
  })

  describe('applyLoginResponse', () => {
    it('hydrates user, departments, and picks first dept when nothing is persisted', () => {
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload())

      expect(s.user).toEqual({ username: 'tester', is_superadmin: false })
      expect(s.departments).toHaveLength(2)
      expect(s.activeDepartmentId).toBe(DEPT_A.id)
      expect(s.hydrated).toBe(true)
      expect(s.isAuthenticated).toBe(true)

      // Persistence: both caches written.
      expect(localStorage.getItem('activeDepartment')).toBe(DEPT_A.id)
      const cached = JSON.parse(localStorage.getItem('session')!)
      expect(cached.user.username).toBe('tester')
      expect(cached.departments).toHaveLength(2)
    })

    it('honours a persisted activeDepartment when it is still a member', () => {
      localStorage.setItem('activeDepartment', DEPT_B.id)
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload())

      expect(s.activeDepartmentId).toBe(DEPT_B.id)
      expect(s.activeDepartment?.slug).toBe('bravo')
    })

    it('falls back to the first dept when the persisted id is no longer a member', () => {
      localStorage.setItem('activeDepartment', 'stale-id-not-in-payload')
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload())

      expect(s.activeDepartmentId).toBe(DEPT_A.id)
    })

    it('leaves activeDepartmentId null when the user has zero departments', () => {
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload({ departments: [] }))
      expect(s.activeDepartmentId).toBeNull()
      expect(s.activeDepartment).toBeNull()
    })
  })

  describe('hydrate', () => {
    it('returns false and clears state when /api/me responds 401', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
      )
      // Seed cache so we can assert clear() actually wipes it.
      localStorage.setItem(
        'session',
        JSON.stringify({ user: { username: 'tester', is_superadmin: false }, departments: [DEPT_A] }),
      )
      const s = useSessionStore()
      const ok = await s.hydrate()

      expect(ok).toBe(false)
      expect(s.user).toBeNull()
      expect(localStorage.getItem('session')).toBeNull()
    })

    it('replays cache and returns true when /api/me is 200 with cache present', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 })),
      )
      localStorage.setItem(
        'session',
        JSON.stringify({
          user: { username: 'tester', is_superadmin: false },
          departments: [DEPT_A, DEPT_B],
        }),
      )
      localStorage.setItem('activeDepartment', DEPT_B.id)

      const s = useSessionStore()
      const ok = await s.hydrate()

      expect(ok).toBe(true)
      expect(s.user?.username).toBe('tester')
      expect(s.activeDepartmentId).toBe(DEPT_B.id)
      expect(s.hydrated).toBe(true)
    })

    it('returns false and clears when /api/me is 200 but the cache was wiped', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 })),
      )
      // No cache seeded.
      const s = useSessionStore()
      const ok = await s.hydrate()

      expect(ok).toBe(false)
      expect(s.user).toBeNull()
    })
  })

  describe('switchDepartment', () => {
    it('updates state + localStorage when the target is a member', async () => {
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload())
      expect(s.activeDepartmentId).toBe(DEPT_A.id)

      await s.switchDepartment(DEPT_B.id)
      expect(s.activeDepartmentId).toBe(DEPT_B.id)
      expect(localStorage.getItem('activeDepartment')).toBe(DEPT_B.id)
    })

    it('throws when the target id is not a member', async () => {
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload())

      await expect(s.switchDepartment('not-a-member')).rejects.toThrow(
        /not in current session/i,
      )
      // State must not have moved.
      expect(s.activeDepartmentId).toBe(DEPT_A.id)
    })
  })

  describe('RBAC getters', () => {
    it('analyst can assess but cannot edit dept config or manage members', () => {
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload({ departments: [DEPT_A] }))
      expect(s.activeRole).toBe('analyst')
      expect(s.canAssess).toBe(true)
      expect(s.canEditDeptConfig).toBe(false)
      expect(s.canManageMembers).toBe(false)
      expect(s.canManageDepartments).toBe(false)
    })

    it('dept_lead can edit dept config + manage members but not manage departments', () => {
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload({ departments: [DEPT_B] }))
      expect(s.activeRole).toBe('dept_lead')
      expect(s.canAssess).toBe(true)
      expect(s.canEditDeptConfig).toBe(true)
      expect(s.canHarmonize).toBe(true)
      expect(s.canManageMembers).toBe(true)
      expect(s.canManageDepartments).toBe(false)
    })

    it('viewer cannot assess', () => {
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload({ departments: [DEPT_C_VIEWER] }))
      expect(s.activeRole).toBe('viewer')
      expect(s.canAssess).toBe(false)
      expect(s.canEditDeptConfig).toBe(false)
    })

    it('superadmin overrides every per-dept permission, including viewer-role membership', () => {
      const s = useSessionStore()
      s.applyLoginResponse(
        loginPayload({ is_superadmin: true, departments: [DEPT_C_VIEWER] }),
      )
      expect(s.isSuperadmin).toBe(true)
      expect(s.activeRole).toBe('viewer')
      expect(s.canAssess).toBe(true)
      expect(s.canEditDeptConfig).toBe(true)
      expect(s.canManageDepartments).toBe(true)
    })

    it('all RBAC getters are false when unauthenticated', () => {
      const s = useSessionStore()
      expect(s.isAuthenticated).toBe(false)
      expect(s.canAssess).toBe(false)
      expect(s.canEditDeptConfig).toBe(false)
      expect(s.canManageDepartments).toBe(false)
    })
  })

  describe('clear', () => {
    it('wipes all state and persisted caches', () => {
      const s = useSessionStore()
      s.applyLoginResponse(loginPayload())
      s.clear()

      expect(s.user).toBeNull()
      expect(s.departments).toEqual([])
      expect(s.activeDepartmentId).toBeNull()
      expect(s.hydrated).toBe(false)
      expect(localStorage.getItem('session')).toBeNull()
      expect(localStorage.getItem('activeDepartment')).toBeNull()
    })
  })
})
