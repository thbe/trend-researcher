<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listBusinessCases, assessBatch, type BusinessCase, type AssessBatchResponse } from '@/api/assessment'
import { formatRelative } from '@/lib/format'

const router = useRouter()
const items = ref<BusinessCase[]>([])
const loading = ref(false)
const assessing = ref(false)
const error = ref<string | null>(null)
const lastResult = ref<AssessBatchResponse | null>(null)

const headers = [
  { title: 'Topic', key: 'title', sortable: false },
  { title: 'Verdict', key: 'relevance_verdict', sortable: false, width: '120px' },
  { title: 'Reason', key: 'relevance_reason', sortable: false },
  { title: 'Model', key: 'model_used', sortable: false, width: '180px' },
  { title: 'Assessed', key: 'generated_at', sortable: false, width: '140px' },
]

function verdictColor(verdict: string): string {
  if (verdict === 'relevant') return 'success'
  if (verdict === 'not-relevant') return 'grey'
  return 'warning'
}

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await listBusinessCases()
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

async function runAssessment() {
  assessing.value = true
  error.value = null
  lastResult.value = null
  try {
    lastResult.value = await assessBatch()
    await load() // refresh table
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    assessing.value = false
  }
}

function goToTopic(topicId: string) {
  router.push({ name: 'topic-detail', params: { id: topicId } })
}

onMounted(load)
</script>

<template>
  <div>
    <div class="d-flex align-center mb-4">
      <div>
        <h1 class="text-h5 font-weight-medium">AI Assessment</h1>
        <div class="text-body-2 text-medium-emphasis mt-1">
          Retail relevance assessment of trending topics
        </div>
      </div>
      <v-spacer />
      <v-btn
        color="primary"
        prepend-icon="mdi-brain"
        :loading="assessing"
        :disabled="assessing"
        @click="runAssessment"
      >
        Assess Unassessed Topics
      </v-btn>
    </div>

    <v-alert
      v-if="lastResult"
      type="success"
      variant="tonal"
      density="comfortable"
      class="mb-4"
      closable
      @click:close="lastResult = null"
    >
      Assessed {{ lastResult.assessed }} topic(s): {{ lastResult.relevant }} relevant,
      {{ lastResult.assessed - lastResult.relevant }} not relevant.
    </v-alert>

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      density="comfortable"
      class="mb-4"
      :text="error"
    />

    <v-data-table
      :headers="headers"
      :items="items"
      :loading="loading"
      density="comfortable"
      hover
      no-data-text="No assessments yet — click 'Assess Unassessed Topics' to start."
      loading-text="Loading business cases…"
    >
      <template #item.title="{ item }">
        <a
          href="#"
          class="text-decoration-none font-weight-medium"
          @click.prevent="goToTopic(item.topic_id)"
        >
          {{ item.title }}
        </a>
      </template>
      <template #item.relevance_verdict="{ item }">
        <v-chip
          :color="verdictColor(item.relevance_verdict)"
          size="small"
          variant="tonal"
          label
        >
          {{ item.relevance_verdict }}
        </v-chip>
      </template>
      <template #item.relevance_reason="{ item }">
        <span class="text-body-2 text-medium-emphasis">
          {{ item.relevance_reason.length > 100 ? item.relevance_reason.slice(0, 100) + '…' : item.relevance_reason }}
        </span>
      </template>
      <template #item.model_used="{ item }">
        <span class="text-caption">{{ item.model_used }}</span>
      </template>
      <template #item.generated_at="{ item }">
        {{ formatRelative(item.generated_at) }}
      </template>
    </v-data-table>
  </div>
</template>
