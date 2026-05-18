<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listTopics, type Topic } from '@/api/topics'
import { ApiError } from '@/api/client'
import { formatLongevity, formatRelative } from '@/lib/format'

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

const items = ref<Topic[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const itemsPerPage = ref(20)
const sortBy = ref<SortItem[]>([{ key: 'last_seen_at', order: 'desc' }])
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
    const resp = await listTopics(sort, options.itemsPerPage)
    items.value = resp.topics
    totalItems.value = resp.topics.length
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
  itemsPerPage.value = options.itemsPerPage
  sortBy.value = options.sortBy
  void load(options)
}

function onRowClick(_event: Event, row: { item: Topic }) {
  router.push({ name: 'topic-detail', params: { id: row.item.id } })
}

onMounted(() => {
  void load({
    page: 1,
    itemsPerPage: itemsPerPage.value,
    sortBy: sortBy.value,
  })
})
</script>

<template>
  <div>
    <div class="d-flex align-end mb-4">
      <div>
        <h1 class="text-h5 font-weight-medium">Topics</h1>
        <div v-if="subtitleText" class="text-body-2 text-medium-emphasis mt-1">
          {{ subtitleText }} · sorted {{ echoedSort }}
        </div>
      </div>
    </div>

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      density="comfortable"
      class="mb-4"
      :text="error"
    />

    <v-data-table-server
      :headers="headers"
      :items="items"
      :items-length="totalItems"
      :loading="loading"
      :items-per-page="itemsPerPage"
      :sort-by="sortBy"
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
  </div>
</template>

<style scoped>
:deep(.v-data-table__tr) {
  cursor: pointer;
}
</style>
