<script setup lang="ts">
// Sources — unified catalog + subscriptions view.
//
// This is the SINGLE page for all source management. It merges the former
// "Sources — Connectors" (tech config CRUD) and "Sources — Subscriptions"
// (per-dept opt-in toggles) into one card-grid surface:
//
//   * Available card  -> non-owned, off       -> subscribe switch
//   * Subscribed card -> non-owned, on        -> subscribe switch (toggle off)
//   * Owned card      -> owner dept           -> locked switch + edit / cleanup / delete
//
// Superadmin sees every catalog row regardless of dept and may edit / delete
// any of them (including ownership reassignment via the edit dialog).
//
// Data model note: the cards are driven by /api/department-sources which
// already returns the full catalog with `owned` + `enabled` (subscription)
// + read-only connector fields. Mutations to connector fields go through
// /api/crawl-config (owner-only) — we just refresh after a successful PUT.

import { computed, onMounted, ref } from 'vue'

import {
  listDepartmentSources,
  updateDepartmentSource,
  type DepartmentSource,
} from '@/api/departmentSources'
import {
  createCrawlConfig,
  updateCrawlConfig,
  deleteCrawlConfig,
  type CrawlConfigCreate,
  type CrawlConfigUpdate,
} from '@/api/crawlConfig'
import { listDepartments, type Department } from '@/api/departments'
import { cleanupOrphanTopics, cleanupTopics, type TopicCleanupResponse } from '@/api/topics'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const isSuperadmin = computed(() => session.isSuperadmin)
const activeDeptName = computed(() => session.activeDepartment?.name ?? '—')

const sources = ref<DepartmentSource[]>([])
const departments = ref<Department[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)
// Per-row saving flags so toggling one row doesn't spinner the whole page.
const saving = ref<Record<string, boolean>>({})

const departmentOptions = computed(() =>
  departments.value.map((d) => ({ title: d.name, value: d.id })),
)

// A user can edit/delete a source if they own it OR they are superadmin.
function canManage(src: DepartmentSource): boolean {
  return isSuperadmin.value || src.owned
}

// Three-card-per-row grid summary counts shown above the catalog.
const counts = computed(() => {
  const owned = sources.value.filter((s) => s.owned).length
  const subscribed = sources.value.filter((s) => !s.owned && s.enabled).length
  const available = sources.value.length - owned - subscribed
  return { total: sources.value.length, owned, subscribed, available }
})

async function load() {
  loading.value = true
  error.value = null
  try {
    const tasks: Promise<unknown>[] = [
      listDepartmentSources().then((r) => (sources.value = r.sources)),
    ]
    // Superadmin needs the dept dropdown options for add / reassign dialogs.
    if (isSuperadmin.value) {
      tasks.push(listDepartments().then((r) => (departments.value = r.departments)))
    }
    await Promise.all(tasks)
  } catch (e: any) {
    error.value = e.message || 'Failed to load sources'
  } finally {
    loading.value = false
  }
}

async function toggle(src: DepartmentSource, next: boolean) {
  // Optimistic local update; revert on error.
  const prev = src.enabled
  src.enabled = next
  saving.value[src.source_name] = true
  error.value = null
  try {
    const updated = await updateDepartmentSource(src.source_name, next)
    Object.assign(src, updated)
    success.value = `${src.source_name}: ${next ? 'subscribed' : 'unsubscribed'}`
  } catch (e: any) {
    src.enabled = prev
    error.value = e.message || `Failed to update ${src.source_name}`
  } finally {
    saving.value[src.source_name] = false
  }
}

function statusColor(src: DepartmentSource): string {
  if (src.owned) return 'primary'
  if (src.enabled) return 'success'
  return 'medium-emphasis'
}

function statusLabel(src: DepartmentSource): string {
  if (src.owned) return 'Owned'
  if (src.enabled) return 'Subscribed'
  return 'Available'
}

function statusIcon(src: DepartmentSource): string {
  if (src.owned) return 'mdi-shield-star-outline'
  if (src.enabled) return 'mdi-check-circle-outline'
  return 'mdi-circle-outline'
}

// --- Add Source dialog -----------------------------------------------------

const addDialog = ref(false)
const newSource = ref<CrawlConfigCreate>({
  source_name: '',
  enabled: true,
  top_n: 100,
  capture_summary: true,
  verify_ssl: true,
  feed_url: null,
  department_id: undefined,
})
const addLoading = ref(false)

function openAddDialog() {
  newSource.value = {
    source_name: '',
    enabled: true,
    top_n: 100,
    capture_summary: true,
    verify_ssl: true,
    feed_url: null,
    department_id: undefined,
  }
  addDialog.value = true
}

const addDisabled = computed(() => {
  if (!newSource.value.source_name) return true
  if (isSuperadmin.value && !newSource.value.department_id) return true
  return false
})

async function addSource() {
  addLoading.value = true
  error.value = null
  try {
    const payload: CrawlConfigCreate = { ...newSource.value }
    if (!payload.department_id) delete payload.department_id
    await createCrawlConfig(payload)
    addDialog.value = false
    success.value = `Added ${payload.source_name}`
    await load()
  } catch (e: any) {
    error.value = e.message || 'Failed to create source'
  } finally {
    addLoading.value = false
  }
}

// --- Edit dialog -----------------------------------------------------------

const editDialog = ref(false)
const editTarget = ref<DepartmentSource | null>(null)
const editForm = ref({
  top_n: 100,
  feed_url: '' as string | null,
  capture_summary: true,
  verify_ssl: true,
  enabled: true,
  department_id: '' as string,
})
const editLoading = ref(false)

function openEditDialog(src: DepartmentSource) {
  editTarget.value = src
  editForm.value = {
    top_n: src.top_n,
    feed_url: src.feed_url,
    capture_summary: src.capture_summary,
    verify_ssl: src.verify_ssl,
    // department-sources doesn't expose the connector's own enabled flag
    // (only the subscription's). The connector is implicitly enabled when
    // it's listed, so default to true; superadmin can flip it off here.
    enabled: true,
    department_id: src.owner_department_id,
  }
  editDialog.value = true
}

async function saveEdit() {
  if (!editTarget.value) return
  editLoading.value = true
  error.value = null
  try {
    const payload: CrawlConfigUpdate = {
      top_n: editForm.value.top_n,
      feed_url: editForm.value.feed_url,
      capture_summary: editForm.value.capture_summary,
      verify_ssl: editForm.value.verify_ssl,
      enabled: editForm.value.enabled,
    }
    if (
      isSuperadmin.value &&
      editForm.value.department_id &&
      editForm.value.department_id !== editTarget.value.owner_department_id
    ) {
      payload.department_id = editForm.value.department_id
    }
    await updateCrawlConfig(editTarget.value.source_name, payload)
    success.value = `Updated ${editTarget.value.source_name}`
    editDialog.value = false
    await load()
  } catch (e: any) {
    error.value = e.message || 'Failed to update source'
  } finally {
    editLoading.value = false
  }
}

// --- Delete dialog ---------------------------------------------------------

const deleteDialog = ref(false)
const deleteTarget = ref<string | null>(null)
const deleteLoading = ref(false)

function confirmDelete(sourceName: string) {
  deleteTarget.value = sourceName
  deleteDialog.value = true
}

async function doDelete() {
  if (!deleteTarget.value) return
  deleteLoading.value = true
  error.value = null
  try {
    await deleteCrawlConfig(deleteTarget.value)
    success.value = `Deleted ${deleteTarget.value}`
    deleteDialog.value = false
    deleteTarget.value = null
    await load()
  } catch (e: any) {
    error.value = e.message || 'Failed to delete source'
  } finally {
    deleteLoading.value = false
  }
}

// --- Cleanup dialog (per-source or global by age) --------------------------

const cleanupDialog = ref(false)
const cleanupForm = ref<{ source_name: string | null; older_than_days: number | null; mode: 'age' | 'all' }>({
  source_name: null,
  older_than_days: 30,
  mode: 'age',
})
const cleanupLoading = ref(false)
const cleanupResult = ref<TopicCleanupResponse | null>(null)
const cleanupError = ref<string | null>(null)

function openCleanupDialog(sourceName: string | null) {
  cleanupForm.value = {
    source_name: sourceName,
    older_than_days: 30,
    mode: 'age',
  }
  cleanupResult.value = null
  cleanupError.value = null
  cleanupDialog.value = true
}

async function doCleanup() {
  cleanupLoading.value = true
  cleanupError.value = null
  cleanupResult.value = null
  try {
    const olderThanDays =
      cleanupForm.value.mode === 'all' ? null : cleanupForm.value.older_than_days
    cleanupResult.value = await cleanupTopics({
      source_name: cleanupForm.value.source_name,
      older_than_days: olderThanDays,
    })
  } catch (e: any) {
    cleanupError.value = e.message || 'Cleanup failed'
  } finally {
    cleanupLoading.value = false
  }
}

// --- Orphan cleanup --------------------------------------------------------

const orphanDialog = ref(false)
const orphanLoading = ref(false)
const orphanResult = ref<TopicCleanupResponse | null>(null)
const orphanError = ref<string | null>(null)

function openOrphanDialog() {
  orphanResult.value = null
  orphanError.value = null
  orphanDialog.value = true
}

async function doOrphanCleanup() {
  orphanLoading.value = true
  orphanError.value = null
  orphanResult.value = null
  try {
    orphanResult.value = await cleanupOrphanTopics()
  } catch (e: any) {
    orphanError.value = e.message || 'Orphan cleanup failed'
  } finally {
    orphanLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="d-flex align-end flex-wrap ga-2 mb-4">
      <div class="flex-grow-1">
        <h1 class="text-h5 font-weight-medium">Sources</h1>
        <div class="text-caption text-medium-emphasis mt-1">
          Catalog of every source plus your subscriptions for
          <strong>{{ activeDeptName }}</strong>.
          Owned sources are always on; available sources can be toggled anytime.
        </div>
      </div>
      <v-btn
        color="warning"
        variant="tonal"
        prepend-icon="mdi-broom"
        @click="openCleanupDialog(null)"
      >
        Cleanup
      </v-btn>
      <v-btn
        color="warning"
        variant="tonal"
        prepend-icon="mdi-link-variant-off"
        @click="openOrphanDialog"
      >
        Clean Orphans
      </v-btn>
      <v-btn color="primary" prepend-icon="mdi-plus" @click="openAddDialog">
        Add Source
      </v-btn>
    </div>

    <!-- Summary tiles: total / owned / subscribed / available -->
    <v-row v-if="!loading && sources.length > 0" class="mb-4" dense>
      <v-col cols="6" sm="3">
        <v-card variant="outlined" class="pa-3">
          <div class="text-caption text-medium-emphasis">Total catalog</div>
          <div class="text-h5 font-weight-medium">{{ counts.total }}</div>
        </v-card>
      </v-col>
      <v-col cols="6" sm="3">
        <v-card variant="outlined" class="pa-3">
          <div class="text-caption text-medium-emphasis">
            <v-icon icon="mdi-shield-star-outline" size="14" color="primary" class="mr-1" />
            Owned
          </div>
          <div class="text-h5 font-weight-medium text-primary">{{ counts.owned }}</div>
        </v-card>
      </v-col>
      <v-col cols="6" sm="3">
        <v-card variant="outlined" class="pa-3">
          <div class="text-caption text-medium-emphasis">
            <v-icon icon="mdi-check-circle-outline" size="14" color="success" class="mr-1" />
            Subscribed
          </div>
          <div class="text-h5 font-weight-medium text-success">{{ counts.subscribed }}</div>
        </v-card>
      </v-col>
      <v-col cols="6" sm="3">
        <v-card variant="outlined" class="pa-3">
          <div class="text-caption text-medium-emphasis">
            <v-icon icon="mdi-circle-outline" size="14" class="mr-1" />
            Available
          </div>
          <div class="text-h5 font-weight-medium text-medium-emphasis">{{ counts.available }}</div>
        </v-card>
      </v-col>
    </v-row>

    <v-alert v-if="error" type="error" variant="tonal" density="comfortable" closable class="mb-4" @click:close="error = null">
      {{ error }}
    </v-alert>

    <v-alert v-if="success" type="success" variant="tonal" density="comfortable" closable class="mb-4" @click:close="success = null">
      {{ success }}
    </v-alert>

    <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-4" />

    <!-- Empty state -->
    <v-card
      v-if="!loading && sources.length === 0"
      variant="outlined"
      class="text-center pa-8"
    >
      <v-icon icon="mdi-rss-off" size="48" color="medium-emphasis" class="mb-3" />
      <div class="text-h6 font-weight-medium mb-2">No sources in the catalog</div>
      <div class="text-body-2 text-medium-emphasis">
        Click <strong>Add Source</strong> above to register a connector for your department.
      </div>
    </v-card>

    <!-- Source cards grid -->
    <v-row v-if="!loading && sources.length > 0" dense>
      <v-col
        v-for="src in sources"
        :key="src.source_name"
        cols="12"
        sm="6"
        lg="4"
      >
        <v-card
          variant="outlined"
          :class="['source-card h-100', { 'source-card--owned': src.owned, 'source-card--enabled': !src.owned && src.enabled }]"
        >
          <v-card-item>
            <template #prepend>
              <v-avatar :color="statusColor(src) === 'medium-emphasis' ? undefined : statusColor(src)" variant="tonal" size="40">
                <v-icon :icon="statusIcon(src)" :color="statusColor(src) === 'medium-emphasis' ? 'medium-emphasis' : undefined" />
              </v-avatar>
            </template>
            <v-card-title class="text-body-1 font-weight-medium pa-0">
              {{ src.source_name }}
            </v-card-title>
            <v-card-subtitle class="pa-0 mt-1">
              <v-chip
                :color="statusColor(src)"
                size="x-small"
                variant="tonal"
                label
                :prepend-icon="statusIcon(src)"
              >
                {{ statusLabel(src) }}
              </v-chip>
            </v-card-subtitle>
            <template #append>
              <v-tooltip
                v-if="src.owned"
                text="Your department owns this source — always active, cannot be toggled."
                location="start"
              >
                <template #activator="{ props }">
                  <div v-bind="props">
                    <v-switch
                      :model-value="true"
                      disabled
                      color="primary"
                      hide-details
                      inset
                      density="compact"
                    />
                  </div>
                </template>
              </v-tooltip>
              <v-switch
                v-else
                :model-value="src.enabled"
                :loading="saving[src.source_name]"
                :disabled="saving[src.source_name]"
                color="primary"
                hide-details
                inset
                density="compact"
                @update:model-value="(v) => toggle(src, v === true)"
              />
            </template>
          </v-card-item>
          <v-divider />
          <v-card-text class="pt-3 pb-2">
            <div class="d-flex flex-column ga-1 text-caption">
              <div>
                <v-icon icon="mdi-domain" size="14" class="mr-1 text-medium-emphasis" />
                <span class="text-medium-emphasis">Owner:</span>
                <strong class="ml-1">{{ src.owner_department_name }}</strong>
              </div>
              <div>
                <v-icon icon="mdi-counter" size="14" class="mr-1 text-medium-emphasis" />
                <span class="text-medium-emphasis">Top N:</span>
                <strong class="ml-1">{{ src.top_n }}</strong>
                <v-icon
                  :icon="src.verify_ssl ? 'mdi-lock-check-outline' : 'mdi-lock-off-outline'"
                  :color="src.verify_ssl ? 'success' : 'warning'"
                  size="14"
                  class="ml-3 mr-1"
                />
                <span class="text-medium-emphasis">SSL</span>
                <v-icon
                  :icon="src.capture_summary ? 'mdi-text-box-check-outline' : 'mdi-text-box-remove-outline'"
                  :color="src.capture_summary ? 'success' : 'medium-emphasis'"
                  size="14"
                  class="ml-3 mr-1"
                />
                <span class="text-medium-emphasis">Summary</span>
              </div>
              <div v-if="src.feed_url" class="text-truncate">
                <v-icon icon="mdi-link-variant" size="14" class="mr-1 text-medium-emphasis" />
                <a :href="src.feed_url" target="_blank" rel="noopener noreferrer" class="text-decoration-none text-primary">
                  {{ src.feed_url }}
                </a>
              </div>
              <div v-else class="text-disabled">
                <v-icon icon="mdi-link-off" size="14" class="mr-1" />
                no feed url
              </div>
            </div>
          </v-card-text>
          <v-divider v-if="canManage(src)" />
          <v-card-actions v-if="canManage(src)" class="px-3 py-1">
            <v-btn
              size="small"
              variant="text"
              prepend-icon="mdi-pencil"
              @click="openEditDialog(src)"
            >
              Edit
            </v-btn>
            <v-btn
              size="small"
              variant="text"
              color="warning"
              prepend-icon="mdi-broom"
              @click="openCleanupDialog(src.source_name)"
            >
              Cleanup
            </v-btn>
            <v-spacer />
            <v-btn
              size="small"
              variant="text"
              color="error"
              icon="mdi-delete"
              @click="confirmDelete(src.source_name)"
            />
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <!-- Add Source Dialog -->
    <v-dialog v-model="addDialog" max-width="500">
      <v-card>
        <v-card-title>Add New Source</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="newSource.source_name"
            label="Source Name"
            hint="Unique identifier (e.g., 'bbc_rss')"
            persistent-hint
            class="mb-3"
          />
          <v-select
            v-if="isSuperadmin"
            v-model="newSource.department_id"
            :items="departmentOptions"
            label="Owner Department"
            hint="Department this source belongs to (required)"
            persistent-hint
            class="mb-3"
          />
          <v-text-field
            v-model="newSource.feed_url"
            label="Feed URL"
            hint="RSS/Atom feed URL"
            persistent-hint
            class="mb-3"
          />
          <v-text-field
            v-model.number="newSource.top_n"
            label="Top N"
            type="number"
            min="1"
            max="500"
            class="mb-3"
          />
          <v-switch
            v-model="newSource.enabled"
            label="Enabled"
            color="primary"
            hide-details
            class="mb-2"
          />
          <v-switch
            v-model="newSource.capture_summary"
            label="Capture Summary"
            color="primary"
            hide-details
            class="mb-2"
          />
          <v-switch
            v-model="newSource.verify_ssl"
            label="Verify SSL"
            color="primary"
            hide-details
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="addDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            :loading="addLoading"
            :disabled="addDisabled"
            @click="addSource"
          >
            Add
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Edit Source Dialog -->
    <v-dialog v-model="editDialog" max-width="500">
      <v-card>
        <v-card-title>Edit Source: {{ editTarget?.source_name }}</v-card-title>
        <v-card-text>
          <v-select
            v-if="isSuperadmin"
            v-model="editForm.department_id"
            :items="departmentOptions"
            label="Owner Department"
            hint="Reassign this source to another department (superadmin only)"
            persistent-hint
            class="mb-3"
          />
          <v-text-field
            v-model="editForm.feed_url"
            label="Feed URL"
            hint="RSS/Atom feed URL"
            persistent-hint
            class="mb-3"
          />
          <v-text-field
            v-model.number="editForm.top_n"
            label="Top N"
            type="number"
            min="1"
            max="500"
            class="mb-3"
          />
          <v-switch
            v-model="editForm.enabled"
            label="Enabled (crawler picks up this source)"
            color="primary"
            hide-details
            class="mb-2"
          />
          <v-switch
            v-model="editForm.capture_summary"
            label="Capture Summary"
            color="primary"
            hide-details
            class="mb-2"
          />
          <v-switch
            v-model="editForm.verify_ssl"
            label="Verify SSL"
            color="primary"
            hide-details
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="editDialog = false">Cancel</v-btn>
          <v-btn color="primary" :loading="editLoading" @click="saveEdit">Save</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete Confirmation Dialog -->
    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card>
        <v-card-title>Delete Source</v-card-title>
        <v-card-text>
          Are you sure you want to delete <strong>{{ deleteTarget }}</strong>?
          This cannot be undone.
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="deleteDialog = false">Cancel</v-btn>
          <v-btn color="error" :loading="deleteLoading" @click="doDelete">Delete</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Cleanup Dialog -->
    <v-dialog v-model="cleanupDialog" max-width="500" persistent>
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon icon="mdi-broom" class="mr-2" color="warning" />
          Cleanup Topics
        </v-card-title>
        <v-card-text>
          <p class="text-body-2 mb-4">
            <template v-if="cleanupForm.source_name">
              Purge observations from source
              <strong>{{ cleanupForm.source_name }}</strong>.
              Topics with no remaining sources will also be removed.
            </template>
            <template v-else>
              Purge topics across <strong>all sources</strong> based on age.
            </template>
          </p>

          <v-radio-group v-model="cleanupForm.mode" hide-details class="mb-3">
            <v-radio
              label="Only items older than N days"
              value="age"
              color="warning"
            />
            <v-radio
              v-if="cleanupForm.source_name"
              label="All items from this source (ignore age)"
              value="all"
              color="error"
            />
          </v-radio-group>

          <v-text-field
            v-if="cleanupForm.mode === 'age'"
            v-model.number="cleanupForm.older_than_days"
            label="Older than (days)"
            type="number"
            min="0"
            max="3650"
            hint="e.g. 30 for one month, 5 for last work week"
            persistent-hint
          />

          <v-alert
            v-if="cleanupForm.mode === 'all' && cleanupForm.source_name"
            type="warning"
            variant="tonal"
            class="mt-3"
          >
            This will delete ALL topic observations from
            <strong>{{ cleanupForm.source_name }}</strong>, regardless of age.
          </v-alert>

          <v-alert v-if="cleanupError" type="error" class="mt-3" closable @click:close="cleanupError = null">
            {{ cleanupError }}
          </v-alert>

          <v-alert v-if="cleanupResult" type="success" class="mt-3" variant="tonal">
            Deleted
            <strong>{{ cleanupResult.topics_deleted }}</strong> topics
            <span v-if="cleanupResult.source_name">
              and <strong>{{ cleanupResult.topic_sources_deleted }}</strong>
              observations from
              <strong>{{ cleanupResult.source_name }}</strong>
            </span>
            <span v-if="cleanupResult.older_than_days !== null">
              older than {{ cleanupResult.older_than_days }} days
            </span>.
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="cleanupDialog = false">Close</v-btn>
          <v-btn
            color="warning"
            :loading="cleanupLoading"
            :disabled="
              cleanupForm.mode === 'age' &&
              (cleanupForm.older_than_days === null ||
                cleanupForm.older_than_days < 0)
            "
            @click="doCleanup"
          >
            Run Cleanup
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Orphan Cleanup Dialog -->
    <v-dialog v-model="orphanDialog" max-width="480" persistent>
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon icon="mdi-link-variant-off" class="mr-2" color="warning" />
          Clean Orphan Topics
        </v-card-title>
        <v-card-text>
          <p class="mb-2">
            Deletes topics that have no associated source observations
            (i.e. orphans left over from manual edits or partial cleanups).
          </p>
          <p class="text-caption text-medium-emphasis mb-0">
            Safe to run any time — it is a no-op when no orphans exist.
          </p>

          <v-alert v-if="orphanError" type="error" class="mt-3" variant="tonal">
            {{ orphanError }}
          </v-alert>

          <v-alert v-if="orphanResult" type="success" class="mt-3" variant="tonal">
            Deleted <strong>{{ orphanResult.topics_deleted }}</strong> orphan topic(s).
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="orphanDialog = false">Close</v-btn>
          <v-btn
            color="warning"
            :loading="orphanLoading"
            @click="doOrphanCleanup"
          >
            Clean Orphans
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.source-card {
  transition: border-color 150ms ease, box-shadow 150ms ease;
}

.source-card--owned {
  border-color: rgb(var(--v-theme-primary));
}

.source-card--enabled {
  border-color: rgb(var(--v-theme-success));
}

.source-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
</style>
