<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useDisplay } from 'vuetify'
import { useRoute, useRouter } from 'vue-router'
import { listTopics, type Topic } from '@/api/topics'
import { assessBatch } from '@/api/assessment'
import { ApiError } from '@/api/client'
import { formatLongevity, formatRelative } from '@/lib/format'
import { STRINGS } from '@/lib/strings'

interface SortItem {
  key: string
  order?: 'asc' | 'desc'
}

interface DataTableOptions {
  page: number
  itemsPerPage: number
  sortBy: SortItem[]
}

const router = useRouter()
const route = useRoute()
const { mobile } = useDisplay()

// Restore list state from URL query so back-navigation from a detail view
// returns the user to the exact page, page size, and sort they had open.
function parseSortFromQuery(raw: unknown): SortItem[] {
  const s = typeof raw === 'string' && raw.length > 0 ? raw : '-last_seen_at'
  const desc = s.startsWith('-')
  const key = desc ? s.slice(1) : s
  // Map API sort key back to column key (inverse of SORT_KEY_MAP).
  const columnKey = key === 'longevity' ? 'longevity_seconds' : key
  return [{ key: columnKey, order: desc ? 'desc' : 'asc' }]
}

const initialPage = Math.max(1, Number.parseInt(String(route.query.page ?? '1'), 10) || 1)
const initialIpp = (() => {
  const n = Number.parseInt(String(route.query.ipp ?? '20'), 10)
  return [10, 20, 50, 100].includes(n) ? n : 20
})()

const items = ref<Topic[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const page = ref(initialPage)
const itemsPerPage = ref(initialIpp)
const sortBy = ref<SortItem[]>(parseSortFromQuery(route.query.sort))
const totalItems = ref(0)
const echoedSort = ref('-last_seen_at')

// Column key (data-table) -> API sort key (CONTEXT G5 whitelist).
const SORT_KEY_MAP: Record<string, string> = {
  breadth: 'breadth',
  longevity_seconds: 'longevity',
  last_seen_at: 'last_seen_at',
}

const headers = [
  { title: 'Title', key: 'title', sortable: false },
  { title: 'Description', key: 'description', sortable: false },
  { title: 'Source', key: 'source_names', sortable: false, width: '140px' },
  { title: 'Verdict', key: 'relevance_verdict', sortable: false, width: '120px' },
  { title: 'Sources', key: 'breadth', align: 'end' as const, sortable: true },
  {
    title: 'Observed',
    key: 'longevity_seconds',
    align: 'end' as const,
    sortable: true,
  },
  { title: 'Last seen', key: 'last_seen_at', sortable: true },
  {
    title: 'Observations',
    key: 'observation_count',
    align: 'end' as const,
    sortable: false,
  },
]

const subtitleText = computed(() => {
  const n = items.value.length
  if (n === 0) {
    return ''
  }
  const m = items.value.reduce((acc, t) => Math.max(acc, t.breadth), 0)
  return `${n} topic${n === 1 ? '' : 's'} across up to ${m} distinct source${m === 1 ? '' : 's'}`
})

function apiSortString(sort: SortItem[]): string {
  if (sort.length === 0) {
    return '-last_seen_at'
  }
  const first = sort[0]
  const apiKey = SORT_KEY_MAP[first.key] ?? 'last_seen_at'
  const prefix = first.order === 'asc' ? '' : '-'
  return `${prefix}${apiKey}`
}

// Plan 04.5-01 / T06 (D-Q5): truncate description to ~120 chars for the
// list-view subtitle so a long publisher standfirst doesn't blow up row
// height. Full description is shown un-truncated on TopicDetail.vue.
function truncate(text: string | null, max = 120): string {
  if (!text) {
    return ''
  }
  return text.length > max ? `${text.slice(0, max)}…` : text
}

async function load(options: DataTableOptions) {
  loading.value = true
  error.value = null
  try {
    const sort = apiSortString(options.sortBy)
    const offset = (options.page - 1) * options.itemsPerPage
    const resp = await listTopics(sort, options.itemsPerPage, offset)
    items.value = resp.topics
    totalItems.value = resp.total
    echoedSort.value = resp.sort
  } catch (err) {
    if (err instanceof ApiError) {
      error.value = `API error (${err.status}): ${err.message}`
    } else {
      error.value = (err as Error).message
    }
    items.value = []
    totalItems.value = 0
  } finally {
    loading.value = false
  }
}

function onUpdateOptions(options: DataTableOptions) {
  page.value = options.page
  itemsPerPage.value = options.itemsPerPage
  sortBy.value = options.sortBy
  // Persist list state in URL so browser-back from TopicDetail restores it.
  const sortStr = apiSortString(options.sortBy)
  void router.replace({
    query: {
      ...route.query,
      page: String(options.page),
      ipp: String(options.itemsPerPage),
      sort: sortStr,
    },
  })
  void load(options)
}

function onRowClick(_event: Event, row: { item: Topic }) {
  router.push({ name: 'topic-detail', params: { id: row.item.id } })
}

const crawling = ref(false)
const assessing = ref(false)
const actionMessage = ref<string | null>(null)

async function triggerCrawl() {
  crawling.value = true
  actionMessage.value = null
  try {
    const resp = await fetch('/api/crawl', { method: 'POST' })
    if (!resp.ok) throw new Error(`Crawl failed: ${resp.status}`)
    const data = await resp.json()
    actionMessage.value = `Crawl complete — ${data.totals?.inserted ?? 0} new, ${data.totals?.updated ?? 0} updated`
    // Reload topics
    page.value = 1
    void load({ page: 1, itemsPerPage: itemsPerPage.value, sortBy: sortBy.value })
  } catch (e) {
    actionMessage.value = `Crawl error: ${(e as Error).message}`
  } finally {
    crawling.value = false
  }
}

async function triggerAssess() {
  assessing.value = true
  actionMessage.value = null
  try {
    const data = await assessBatch()
    actionMessage.value = `Assessment job started (${data.total_topics} topics queued)`
    // Reload topics to show updated verdicts
    page.value = 1
    void load({ page: 1, itemsPerPage: itemsPerPage.value, sortBy: sortBy.value })
  } catch (e) {
    actionMessage.value = `Assessment error: ${(e as Error).message}`
  } finally {
    assessing.value = false
  }
}

onMounted(() => {
  void load({
    page: page.value,
    itemsPerPage: itemsPerPage.value,
    sortBy: sortBy.value,
  })
})
</script>

<template>
  <div>
    <div class="d-flex align-end mb-4">
      <div>
        <h1 class="text-h5 font-weight-medium">{{ STRINGS.PAGE_TOPICS }}</h1>
        <div class="text-caption text-medium-emphasis mt-1">
          Topics are global across all departments; AI relevance is assessed per department.
        </div>
        <div v-if="subtitleText" class="text-body-2 text-medium-emphasis mt-1">
          {{ subtitleText }} · sorted {{ echoedSort }}
        </div>
      </div>
      <v-spacer />
      <v-btn
        color="secondary"
        variant="tonal"
        :loading="crawling"
        :disabled="crawling || assessing"
        class="mr-2"
        prepend-icon="mdi-refresh"
        @click="triggerCrawl"
      >
        Refresh Topics
      </v-btn>
      <v-btn
        color="primary"
        variant="flat"
        :loading="assessing"
        :disabled="crawling || assessing"
        prepend-icon="mdi-brain"
        @click="triggerAssess"
      >
        Assess Topics
      </v-btn>
    </div>

    <v-alert
      v-if="actionMessage"
      type="info"
      variant="tonal"
      density="comfortable"
      closable
      class="mb-4"
      :text="actionMessage"
    />

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      density="comfortable"
      class="mb-4"
      :text="error"
    />

    <!-- Friendlier empty state: when 0 topics, send the user to Source
         Subscriptions (the most common cause of an empty list is "no sources
         enabled for this department yet"). The data-table itself still
         renders with its own no-data slot below for the inline indicator. -->
    <v-card
      v-if="!loading && totalItems === 0 && !error"
      variant="outlined"
      class="mb-4 text-center pa-8"
    >
      <v-icon icon="mdi-rss-off" size="48" color="medium-emphasis" class="mb-3" />
      <div class="text-h6 font-weight-medium mb-2">No topics for this department yet</div>
      <div class="text-body-2 text-medium-emphasis mb-4">
        Topics show up here once your department is subscribed to (or owns) at least one source
        and the crawler has run.
      </div>
      <div class="d-flex justify-center ga-2 flex-wrap">
        <v-btn
          color="primary"
          variant="flat"
          prepend-icon="mdi-rss"
          :to="{ name: 'source-subscriptions' }"
        >
          Manage Sources
        </v-btn>
        <v-btn
          color="secondary"
          variant="tonal"
          prepend-icon="mdi-refresh"
          :loading="crawling"
          :disabled="crawling || assessing"
          @click="triggerCrawl"
        >
          Run Crawl
        </v-btn>
      </div>
    </v-card>

    <v-data-table-server
      v-if="!mobile"
      :headers="headers"
      :items="items"
      :items-length="totalItems"
      :loading="loading"
      v-model:items-per-page="itemsPerPage"
      v-model:page="page"
      v-model:sort-by="sortBy"
      :items-per-page-options="[10, 20, 50, 100]"
      hover
      density="comfortable"
      no-data-text="No topics yet — run the crawler to populate the store."
      loading-text="Loading topics…"
      @update:options="onUpdateOptions"
      @click:row="onRowClick"
    >
      <template #item.title="{ item }">
        <span class="font-weight-medium">{{ item.title }}</span>
      </template>
      <template #item.description="{ item }">
        <span v-if="item.description" class="text-medium-emphasis">{{
          truncate(item.description)
        }}</span>
        <em v-else class="text-disabled">—</em>
      </template>
      <template #item.source_names="{ item }">
        <template v-if="item.source_names">
          <v-chip v-for="s in item.source_names.split(', ')" :key="s" size="x-small" variant="tonal" class="ma-1">{{ s }}</v-chip>
        </template>
        <span v-else class="text-disabled">—</span>
      </template>
      <template #item.relevance_verdict="{ item }">
        <v-chip
          v-if="item.relevance_verdict"
          :color="item.relevance_verdict === 'relevant' ? 'success' : 'grey'"
          size="small"
          variant="tonal"
          label
        >
          {{ item.relevance_verdict }}
        </v-chip>
        <span v-else class="text-disabled">—</span>
      </template>
      <template #item.longevity_seconds="{ item }">
        {{ formatLongevity(item.longevity_seconds) }}
      </template>
      <template #item.last_seen_at="{ item }">
        {{ formatRelative(item.last_seen_at) }}
      </template>
    </v-data-table-server>

    <!-- Mobile card-list fallback: <600px the data-table cramps 8 columns
         into ~375px making titles wrap to 8+ lines. A card per topic gives
         each item full width with the same data still scannable. -->
    <div v-else>
      <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-3" />
      <div v-if="!loading && items.length === 0" class="text-center text-medium-emphasis py-8">
        No topics yet — run the crawler to populate the store.
      </div>
      <v-card
        v-for="t in items"
        :key="t.id"
        variant="outlined"
        class="mb-3"
        @click="router.push({ name: 'topic-detail', params: { id: t.id } })"
      >
        <v-card-item>
          <div class="d-flex align-start ga-2">
            <div class="flex-grow-1">
              <div class="text-body-1 font-weight-medium">{{ t.title }}</div>
              <div v-if="t.description" class="text-caption text-medium-emphasis mt-1">
                {{ truncate(t.description, 100) }}
              </div>
            </div>
            <v-chip
              v-if="t.relevance_verdict"
              :color="t.relevance_verdict === 'relevant' ? 'success' : 'grey'"
              size="x-small"
              variant="tonal"
              label
            >
              {{ t.relevance_verdict }}
            </v-chip>
          </div>
          <div class="d-flex flex-wrap ga-3 mt-3 text-caption text-medium-emphasis">
            <span>
              <v-icon icon="mdi-source-branch" size="14" class="mr-1" />
              {{ t.breadth }} src
            </span>
            <span>
              <v-icon icon="mdi-clock-outline" size="14" class="mr-1" />
              {{ formatLongevity(t.longevity_seconds) }}
            </span>
            <span>
              <v-icon icon="mdi-eye-outline" size="14" class="mr-1" />
              {{ formatRelative(t.last_seen_at) }}
            </span>
            <span>
              <v-icon icon="mdi-counter" size="14" class="mr-1" />
              {{ t.observation_count }}
            </span>
          </div>
        </v-card-item>
      </v-card>
      <v-pagination
        v-if="totalItems > itemsPerPage"
        v-model="page"
        :length="Math.ceil(totalItems / itemsPerPage)"
        :total-visible="5"
        density="comfortable"
        class="mt-4"
        @update:model-value="(p: number) => onUpdateOptions({ page: p, itemsPerPage, sortBy })"
      />
    </div>
  </div>
</template>

<style scoped>
:deep(.v-data-table__tr) {
  cursor: pointer;
}
</style>
