<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '@/stores/session'
import { STRINGS } from '@/lib/strings'

const session = useSessionStore()

const items = computed(() =>
  session.departments.map((d) => ({
    title: d.name,
    value: d.id,
    role: d.role,
  })),
)

const value = computed({
  get: () => session.activeDepartmentId,
  set: (id: string | null) => {
    if (id) session.switchDepartment(id)
  },
})

const hasMultiple = computed(() => session.departments.length > 1)
</script>

<template>
  <template v-if="session.isAuthenticated">
    <v-select
      v-if="hasMultiple"
      v-model="value"
      :items="items"
      item-title="title"
      item-value="value"
      :label="STRINGS.LABEL_ACTIVE_DEPT"
      variant="outlined"
      density="compact"
      hide-details
      class="dept-switcher"
      style="max-width: 240px"
    />
    <div v-else-if="session.activeDepartment" class="text-body-2 text-medium-emphasis">
      <v-icon size="small" icon="mdi-domain" class="mr-1" />
      {{ session.activeDepartment.name }}
    </div>
  </template>
</template>

<style scoped>
.dept-switcher :deep(.v-field) {
  font-size: 0.875rem;
}
</style>
