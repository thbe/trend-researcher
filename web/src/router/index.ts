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
    redirect: { name: 'topics' },
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
