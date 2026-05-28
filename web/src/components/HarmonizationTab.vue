<script setup lang="ts">
// HarmonizationTab — cross-department harmonization view for a topic.
// Shows all business cases grouped by department + the Net View editor.
// Phase 10, plan 10-05 T06.

import { computed, onMounted, ref, watch } from 'vue'
import {
  getHarmonization,
  deleteHarmonization,
  type HarmonizationResponse,
  type HarmonizationBusinessCase,
} from '@/api/harmonization'
import { useSessionStore } from '@/stores/session'
import BusinessCaseCard from '@/components/BusinessCaseCard.vue'
import NetViewEditor from '@/components/NetViewEditor.vue'

const props = defineProps<{ topicId: string }>()
const session = useSessionStore()

const data = ref<HarmonizationResponse | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

// Group business cases by department
const byDepartment = computed(() => {
  if (!data.value) return []
  const map = new Map<string, { dept: { id: string; name: string }; cases: HarmonizationBusinessCase[] }>()
  for (const bc of data.value.business_cases) {
    const key = bc.department.id
    if (!map.has(key)) {
      map.set(key, { dept: bc.department, cases: [] })
    }
    map.get(key)!.cases.push(bc)
  }
  return [...map.values()]
})

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await getHarmonization(props.topicId)
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

async function handleNetViewSaved() {
  await load()
}

async function handleNetViewDeleted() {
  try {
    await deleteHarmonization(props.topicId)
    await load()
  } catch (err) {
    error.value = (err as Error).message
  }
}

onMounted(load)
watch(() => props.topicId, load)
</script>

<template>
  <div>
    <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-4" />

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />

    <template v-if="data && !loading">
      <!-- Net View section -->
      <NetViewEditor
        :topic-id="props.topicId"
        :net-view="data.net_view"
        :can-edit="session.canHarmonize"
        class="mb-6"
        @saved="handleNetViewSaved"
        @deleted="handleNetViewDeleted"
      />

      <!-- Business Cases by Department -->
      <div class="text-h6 mb-3">
        Business Cases ({{ data.business_cases.length }})
      </div>

      <v-alert
        v-if="data.business_cases.length === 0"
        type="info"
        variant="tonal"
        text="No business cases have been generated for this topic yet."
      />

      <div v-for="group in byDepartment" :key="group.dept.id" class="mb-4">
        <div class="text-subtitle-1 font-weight-medium mb-2">
          <v-icon icon="mdi-domain" size="small" class="mr-1" />
          {{ group.dept.name }}
        </div>
        <div class="d-flex flex-column" style="gap: 8px">
          <BusinessCaseCard
            v-for="bc in group.cases"
            :key="bc.id"
            :bcase="bc as any"
          />
        </div>
      </div>
    </template>
  </div>
</template>
