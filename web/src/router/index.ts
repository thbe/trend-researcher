import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

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
    path: '/config',
    name: 'crawl-config',
    component: () => import('@/views/CrawlConfig.vue'),
  },
  {
    path: '/ai-config',
    name: 'ai-config',
    component: () => import('@/views/AIConfig.vue'),
  },
  {
    path: '/assessment',
    name: 'assessment',
    component: () => import('@/views/Assessment.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Auth guard: redirect to login if session is invalid
router.beforeEach(async (to) => {
  if (to.meta.public) return true

  try {
    const res = await fetch('/api/me')
    if (res.ok) return true
  } catch {
    // network error — fall through to login
  }
  return { name: 'login' }
})

export default router
