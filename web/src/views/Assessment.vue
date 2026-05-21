<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { listBusinessCases, assessBatch, getJob, type BusinessCase, type AssessJob } from '@/api/assessment'
import { formatRelative } from '@/lib/format'

const router = useRouter()
const route = useRoute()
const items = ref<BusinessCase[]>([])
const loading = ref(false)
const assessing = ref(false)
const error = ref<string | null>(null)
const activeJob = ref<AssessJob | null>(null)
const categoryFilter = ref<string | undefined>(route.query.category as string | undefined)

let pollTimer: ReturnType<typeof setInterval> | null = null

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
    items.value = await listBusinessCases(50, categoryFilter.value)
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
  }
}

watch(() => route.query.category, (val) => {
  categoryFilter.value = val as string | undefined
  load()
})

function startPolling(jobId: string) {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const job = await getJob(jobId)
      activeJob.value = job
      if (job.state === 'completed' || job.state === 'failed') {
        stopPolling()
        assessing.value = false
        if (job.state === 'completed') {
          await load() // refresh table
        }
        if (job.state === 'failed' && job.error) {
          error.value = job.error
        }
      }
    } catch {
      // Keep polling on transient errors
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function runAssessment() {
  assessing.value = true
  error.value = null
  activeJob.value = null
  try {
    const resp = await assessBatch()
    activeJob.value = {
      id: resp.job_id,
      state: 'pending',
      total_topics: resp.total_topics,
      completed_topics: 0,
      failed_topics: 0,
      results: null,
      error: null,
      created_at: null,
      started_at: null,
      finished_at: null,
    }
    startPolling(resp.job_id)
  } catch (err) {
    error.value = (err as Error).message
    assessing.value = false
  }
}

function goToTopic(topicId: string) {
  router.push({ name: 'topic-detail', params: { id: topicId } })
}

function onFilterChange(val: string | undefined) {
  const query = val ? { category: val } : {}
  router.replace({ query })
  load()
}

const jobProgress = () => {
  if (!activeJob.value || activeJob.value.total_topics === 0) return 0
  return Math.round((activeJob.value.completed_topics / activeJob.value.total_topics) * 100)
}

onMounted(load)
onUnmounted(stopPolling)
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
      <v-chip-group v-model="categoryFilter" class="mr-4" @update:modelValue="onFilterChange">
        <v-chip value="opportunity" color="success" variant="tonal" filter>Opportunities</v-chip>
        <v-chip value="risk" color="error" variant="tonal" filter>Risks</v-chip>
        <v-chip value="neutral" color="grey" variant="tonal" filter>Neutral</v-chip>
      </v-chip-group>
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

    <!-- Job progress indicator -->
    <v-card v-if="activeJob" variant="tonal" class="mb-4 pa-4">
      <div class="d-flex align-center mb-2">
        <v-icon :color="activeJob.state === 'failed' ? 'error' : 'primary'" class="mr-2">
          {{ activeJob.state === 'completed' ? 'mdi-check-circle' : activeJob.state === 'failed' ? 'mdi-alert-circle' : 'mdi-progress-clock' }}
        </v-icon>
        <span class="text-body-1 font-weight-medium">
          Assessment Job —
          <span class="text-capitalize">{{ activeJob.state }}</span>
        </span>
        <v-spacer />
        <span class="text-body-2 text-medium-emphasis">
          {{ activeJob.completed_topics }} / {{ activeJob.total_topics }} topics
          <span v-if="activeJob.failed_topics > 0" class="text-error">
            ({{ activeJob.failed_topics }} failed)
          </span>
        </span>
      </div>
      <v-progress-linear
        :model-value="jobProgress()"
        :color="activeJob.state === 'failed' ? 'error' : activeJob.state === 'completed' ? 'success' : 'primary'"
        height="8"
        rounded
      />
      <div v-if="activeJob.state === 'completed' && activeJob.results" class="text-body-2 mt-2 text-medium-emphasis">
        Assessed {{ activeJob.results.assessed }} topic(s): {{ activeJob.results.relevant }} relevant.
      </div>
    </v-card>

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
