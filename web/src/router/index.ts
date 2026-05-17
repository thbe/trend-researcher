import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
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

export default createRouter({
  history: createWebHistory(),
  routes,
})
