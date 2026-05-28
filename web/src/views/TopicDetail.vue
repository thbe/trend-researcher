<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getTopic, type TopicDetail } from '@/api/topics'
import { assessTopic, type BusinessCase } from '@/api/assessment'
import { ApiError } from '@/api/client'
import { formatLongevity, formatRelative } from '@/lib/format'
import { useSessionStore } from '@/stores/session'
import BusinessCaseCard from '@/components/BusinessCaseCard.vue'
import FrameworkPicker from '@/components/FrameworkPicker.vue'

const props = defineProps<{ id: string }>()
const router = useRouter()
const session = useSessionStore()

const topic = ref<TopicDetail | null>(null)
const loading = ref(false)
const errorMsg = ref<string | null>(null)
const notFound = ref(false)

const SOURCE_COLORS: Record<string, string> = {
  hackernews: 'orange',
  nyt_homepage: 'blue-grey-darken-3',
  google_news: 'green',
}

function sourceColor(name: string): string {
  return SOURCE_COLORS[name] ?? 'surface-variant'
}

const truncatedTitle = computed(() => {
  if (!topic.value) {
    return ''
  }
  const t = topic.value.title
  return t.length > 80 ? `${t.slice(0, 79)}…` : t
})

function truncateUrl(url: string): string {
  if (url.length <= 60) {
    return url
  }
  return `${url.slice(0, 30)}…${url.slice(-27)}`
}

const hasMetadata = computed(() => {
  const m = topic.value?.topic_metadata
  return !!m && Object.keys(m).length > 0
})

async function load() {
  loading.value = true
  errorMsg.value = null
  notFound.value = false
  topic.value = null
  try {
    topic.value = await getTopic(props.id)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound.value = true
    } else if (err instanceof ApiError) {
      errorMsg.value = `API error (${err.status}): ${err.message}`
    } else {
      errorMsg.value = (err as Error).message
    }
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push({ name: 'topics' })
}

const assessing = ref(false)
const assessResult = ref<BusinessCase | Record<string, unknown> | null>(null)
const assessError = ref<string | null>(null)
const selectedFrameworkId = ref<string | null>(null)

// Phase 10 T06: when the API exposes a list of per-department business cases
// on TopicDetail, prefer rendering those via BusinessCaseCard. Otherwise
// fall back to the legacy single-shot assess flow (server may not yet
// return business_cases on this endpoint).
const businessCases = computed<BusinessCase[]>(() => topic.value?.business_cases ?? [])
const hasBusinessCases = computed(() => businessCases.value.length > 0)

// Synthesise a BusinessCase-shaped object from the legacy POST /api/assess
// response when possible so we can render it via BusinessCaseCard.
const inlineCase = computed<BusinessCase | null>(() => {
  const r = assessResult.value
  if (!r || typeof r !== 'object') return null
  const candidate = r as Partial<BusinessCase>
  if (typeof candidate.relevance_verdict !== 'string') return null
  return candidate as BusinessCase
})

async function runAssess() {
  if (!session.canAssess) {
    assessError.value = 'You do not have permission to run AI assessment in this department.'
    return
  }
  assessing.value = true
  assessError.value = null
  assessResult.value = null
  try {
    assessResult.value = await assessTopic(props.id, selectedFrameworkId.value)
    // Refresh the topic so any newly persisted business_cases show up.
    await load()
  } catch (err) {
    assessError.value = (err as Error).message
  } finally {
    assessing.value = false
  }
}

onMounted(load)
watch(() => props.id, load)
</script>

<template>
  <div>
    <v-btn
      prepend-icon="mdi-arrow-left"
      class="mb-4"
      density="comfortable"
      @click="goBack"
    >
      Back to topics
    </v-btn>

    <v-progress-linear v-if="loading" indeterminate color="primary" />

    <v-alert
      v-else-if="notFound"
      type="info"
      variant="tonal"
      title="Topic not found"
      text="This topic no longer exists or the id is incorrect."
      class="mt-4"
    />

    <v-alert
      v-else-if="errorMsg"
      type="error"
      variant="tonal"
      :text="errorMsg"
      class="mt-4"
    />

    <v-card v-else-if="topic" variant="flat" class="mt-2">
      <v-card-title class="text-h5 text-wrap">
        {{ truncatedTitle }}
      </v-card-title>
      <v-card-text>
        <p v-if="topic.description" class="text-body-1 mb-4">
          {{ topic.description }}
        </p>
        <em v-else class="text-medium-emphasis d-block mb-4">No description.</em>

        <v-row dense class="mb-2">
          <v-col cols="6" sm="4" md="2">
            <div class="text-caption text-medium-emphasis">Sources</div>
            <div class="text-body-1">{{ topic.breadth }}</div>
          </v-col>
          <v-col cols="6" sm="4" md="2">
            <div class="text-caption text-medium-emphasis">Observed</div>
            <div class="text-body-1">
              {{ formatLongevity(topic.longevity_seconds) }}
            </div>
          </v-col>
          <v-col cols="6" sm="4" md="3">
            <div class="text-caption text-medium-emphasis">First seen</div>
            <div class="text-body-2">{{ formatRelative(topic.first_seen_at) }}</div>
          </v-col>
          <v-col cols="6" sm="4" md="3">
            <div class="text-caption text-medium-emphasis">Last seen</div>
            <div class="text-body-2">{{ formatRelative(topic.last_seen_at) }}</div>
          </v-col>
          <v-col cols="6" sm="4" md="2">
            <div class="text-caption text-medium-emphasis">Observations</div>
            <div class="text-body-1">{{ topic.observation_count }}</div>
          </v-col>
        </v-row>

        <v-expansion-panels v-if="hasMetadata" class="my-4" variant="accordion">
          <v-expansion-panel title="Raw metadata">
            <template #text>
              <pre
                class="text-caption"
                style="white-space: pre-wrap; word-break: break-word"
              >{{ JSON.stringify(topic.topic_metadata, null, 2) }}</pre>
            </template>
          </v-expansion-panel>
        </v-expansion-panels>

        <div class="text-h6 mt-6 mb-2">
          AI Assessment
        </div>

        <div class="d-flex align-center mb-3" style="gap: 12px">
          <FrameworkPicker
            v-model="selectedFrameworkId"
            :disabled="assessing || !session.canAssess"
            style="max-width: 280px"
          />
          <v-btn
            color="primary"
            prepend-icon="mdi-brain"
            :loading="assessing"
            :disabled="assessing || !session.canAssess"
            @click="runAssess"
          >
            Assess Topic
          </v-btn>
          <span
            v-if="!session.canAssess"
            class="text-caption text-medium-emphasis"
          >
            Requires analyst role in the active department.
          </span>
        </div>

        <v-alert
          v-if="assessError"
          type="error"
          variant="tonal"
          density="comfortable"
          class="mb-3"
          :text="assessError"
        />

        <!-- Preferred path: backend exposes per-dept business_cases on TopicDetail. -->
        <div v-if="hasBusinessCases" class="d-flex flex-column" style="gap: 12px">
          <BusinessCaseCard
            v-for="bc in businessCases"
            :key="bc.id"
            :bcase="bc"
          />
        </div>

        <!-- Fallback: legacy single-shot assess returned a BusinessCase-shaped object. -->
        <BusinessCaseCard
          v-else-if="inlineCase"
          :bcase="inlineCase"
        />

        <!-- Last-resort fallback: server returned an opaque payload. -->
        <v-card v-else-if="assessResult" variant="outlined" class="mb-4">
          <v-card-text>
            <pre class="text-caption" style="white-space: pre-wrap">{{ JSON.stringify(assessResult, null, 2) }}</pre>
          </v-card-text>
        </v-card>

        <div class="text-h6 mt-6 mb-2">
          Sources ({{ topic.sources.length }})
        </div>
        <div
          v-if="topic.sources.length === 0"
          class="text-medium-emphasis text-body-2"
        >
          No sources recorded for this topic.
        </div>
        <v-list v-else density="compact" lines="two">
          <v-list-item
            v-for="src in topic.sources"
            :key="src.id"
            class="px-2"
          >
            <template #prepend>
              <v-chip
                :color="sourceColor(src.source_name)"
                size="small"
                variant="tonal"
                class="mr-3"
                label
              >
                {{ src.source_name }}
              </v-chip>
            </template>
            <v-list-item-title>
              <a
                :href="src.resolved_url || src.url"
                target="_blank"
                rel="noopener noreferrer"
                class="text-decoration-none"
              >
                {{ truncateUrl(src.resolved_url || src.url) }}
                <v-icon
                  icon="mdi-open-in-new"
                  size="x-small"
                  color="primary"
                  class="ml-1"
                />
              </a>
            </v-list-item-title>
            <v-list-item-subtitle>
              <span v-if="src.native_rank !== null">#{{ src.native_rank }} · </span>
              {{ formatRelative(src.observed_at) }}
            </v-list-item-subtitle>
          </v-list-item>
        </v-list>
      </v-card-text>
    </v-card>
  </div>
</template>
