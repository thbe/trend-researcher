<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '@/stores/session'
import { STRINGS } from '@/lib/strings'

defineProps<{ modelValue?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const session = useSessionStore()

interface NavItem {
  title: string
  icon: string
  to: string
  show: boolean
}

const items = computed<NavItem[]>(() => [
  {
    title: STRINGS.NAV_DASHBOARD,
    icon: 'mdi-view-dashboard-outline',
    to: '/dashboard',
    show: session.isAuthenticated,
  },
  {
    title: STRINGS.NAV_TOPICS,
    icon: 'mdi-format-list-bulleted',
    to: '/topics',
    show: session.isAuthenticated,
  },
  {
    title: STRINGS.NAV_ASSESSMENT,
    icon: 'mdi-brain',
    to: '/assessment',
    show: session.canAssess,
  },
  {
    title: STRINGS.NAV_AI_CONFIG,
    icon: 'mdi-robot-outline',
    to: '/ai-config',
    show: session.canEditDeptConfig,
  },
  {
    title: STRINGS.NAV_SOURCE_SUBSCRIPTIONS,
    icon: 'mdi-rss',
    to: '/source-subscriptions',
    show: session.canEditDeptConfig,
  },
  {
    title: STRINGS.NAV_FRAMEWORK_SETTINGS,
    icon: 'mdi-shape-outline',
    to: '/framework-settings',
    show: session.canEditDeptConfig,
  },
  {
    title: STRINGS.NAV_DEPARTMENTS,
    icon: 'mdi-domain',
    to: '/departments',
    show: session.canManageDepartments,
  },
  {
    title: STRINGS.NAV_CRAWL_CONFIG,
    icon: 'mdi-cog-outline',
    to: '/sources',
    show: session.isSuperadmin,
  },
])

const visibleItems = computed(() => items.value.filter((i) => i.show))
</script>

<template>
  <v-navigation-drawer
    v-if="session.isAuthenticated"
    :model-value="modelValue ?? true"
    @update:model-value="emit('update:modelValue', $event)"
    color="surface"
  >
    <v-list density="comfortable" nav>
      <v-list-item
        v-for="item in visibleItems"
        :key="item.to"
        :to="item.to"
        :prepend-icon="item.icon"
        :title="item.title"
      />
    </v-list>
  </v-navigation-drawer>
</template>
