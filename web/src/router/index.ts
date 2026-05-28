// SPA router — multi-tenant aware (Phase 10 T07).
//
// Route guards use the Pinia session store as the source of truth and the
// /api/me endpoint only as a cookie liveness probe (CONTEXT G2). RBAC is
// enforced via per-route `meta` flags; an unauthorised access bounces to
// /dashboard with a 403 toast surfaced through the UI store.
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'

// Route meta surface. Keep it small and explicit; the guard reads these
// in priority order: superadmin > role-based capability flags.
//
// Capability flags map 1:1 onto the session-store getters of the same
// name (canAssess, canEditDeptConfig, canManageDepartments). The router
// performs the OR-with-superadmin via those getters — we never replicate
// that logic here.
declare module 'vue-router' {
  interface RouteMeta {
    /** Public routes (login) skip every auth check. */
    public?: boolean
    /** Routes restricted to superadmins (cross-tenant admin surfaces). */
    superadminOnly?: boolean
    /** Routes that require `canAssess` (analyst+ in active dept). */
    requireCanAssess?: boolean
    /** Routes that require `canEditDeptConfig` (dept_lead+ in active dept). */
    requireCanEditDeptConfig?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    redirect: { name: 'dashboard' },
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/Dashboard.vue'),
  },
  {
    path: '/topics',
    name: 'topics',
    component: () => import('@/views/TopicList.vue'),
  },
  {
    path: '/topics/:id',
    name: 'topic-detail',
    component: () => import('@/views/TopicDetail.vue'),
    props: true,
  },
  {
    // Plan uses /assess; we keep the legacy /assessment name as the canonical
    // route (Dashboard.vue + NavDrawer push by name) and expose /assess as an
    // alias so links in docs / external referrers keep working.
    path: '/assessment',
    name: 'assessment',
    component: () => import('@/views/Assessment.vue'),
    alias: ['/assess'],
    meta: { requireCanAssess: true },
  },
  {
    path: '/ai-config',
    name: 'ai-config',
    component: () => import('@/views/AIConfig.vue'),
    meta: { requireCanEditDeptConfig: true },
  },
  {
    path: '/source-subscriptions',
    name: 'source-subscriptions',
    component: () => import('@/views/SourceSubscriptions.vue'),
    meta: { requireCanEditDeptConfig: true },
  },
  {
    path: '/framework-settings',
    name: 'framework-settings',
    component: () => import('@/views/FrameworkSettings.vue'),
    meta: { requireCanEditDeptConfig: true },
  },
  {
    // Plan path is /crawl-config; legacy NavDrawer link & PostgreSQL admin
    // bookmarks use /sources. Keep /sources as canonical, /crawl-config as
    // alias for forward-compat with planning doc terminology.
    path: '/sources',
    name: 'sources',
    component: () => import('@/views/CrawlConfig.vue'),
    alias: ['/crawl-config'],
    meta: { superadminOnly: true },
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('@/views/Admin.vue'),
    meta: { superadminOnly: true },
  },
  {
    // Legacy routes redirect to unified admin view
    path: '/users',
    redirect: { name: 'admin' },
  },
  {
    path: '/departments',
    redirect: { name: 'admin' },
  },
  {
    path: '/departments/:id/settings',
    redirect: { name: 'admin' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true

  const session = useSessionStore()

  // Lazy hydrate: on first navigation after a page reload the store is
  // empty even though the cookie may still be valid. hydrate() probes
  // /api/me and replays the cached LoginResponse from localStorage.
  if (!session.isAuthenticated || !session.hydrated) {
    const ok = await session.hydrate()
    if (!ok) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }

  // RBAC: superadmin gate.
  if (to.meta.superadminOnly && !session.isSuperadmin) {
    useUiStore().error(
      `Access denied: "${String(to.name ?? to.path)}" requires superadmin privileges.`,
    )
    return { name: 'dashboard' }
  }

  // RBAC: dept-scoped capability gates. Both getters already OR with
  // isSuperadmin so superadmins pass through transparently.
  if (to.meta.requireCanEditDeptConfig && !session.canEditDeptConfig) {
    useUiStore().error(
      `Access denied: "${String(to.name ?? to.path)}" requires dept lead role in the active department.`,
    )
    return { name: 'dashboard' }
  }

  if (to.meta.requireCanAssess && !session.canAssess) {
    useUiStore().error(
      `Access denied: "${String(to.name ?? to.path)}" requires analyst role in the active department.`,
    )
    return { name: 'dashboard' }
  }

  return true
})

export default router
