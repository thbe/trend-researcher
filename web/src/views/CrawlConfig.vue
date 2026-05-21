<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  listCrawlConfig,
  updateCrawlConfig,
  createCrawlConfig,
  deleteCrawlConfig,
  type CrawlConfig,
  type CrawlConfigCreate,
} from '@/api/crawlConfig'

const configs = ref<CrawlConfig[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const saving = ref<string | null>(null)

// Add dialog state
const addDialog = ref(false)
const newSource = ref<CrawlConfigCreate>({
  source_name: '',
  enabled: true,
  top_n: 100,
  capture_summary: true,
  verify_ssl: true,
  feed_url: null,
})
const addLoading = ref(false)

// Delete confirmation
const deleteDialog = ref(false)
const deleteTarget = ref<string | null>(null)
const deleteLoading = ref(false)

// Edit dialog state
const editDialog = ref(false)
const editSource = ref<CrawlConfig | null>(null)
const editForm = ref({ top_n: 100, feed_url: '' as string | null, capture_summary: true, verify_ssl: true, enabled: true })
const editLoading = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    configs.value = await listCrawlConfig()
  } catch (e: any) {
    error.value = e.message || 'Failed to load config'
  } finally {
    loading.value = false
  }
}

async function toggleEnabled(cfg: CrawlConfig) {
  saving.value = cfg.source_name
  try {
    const updated = await updateCrawlConfig(cfg.source_name, { enabled: !cfg.enabled })
    const idx = configs.value.findIndex((c) => c.source_name === cfg.source_name)
    if (idx >= 0) configs.value[idx] = updated
  } catch (e: any) {
    error.value = e.message || 'Failed to update'
  } finally {
    saving.value = null
  }
}

async function toggleVerifySsl(cfg: CrawlConfig) {
  saving.value = cfg.source_name
  try {
    const updated = await updateCrawlConfig(cfg.source_name, { verify_ssl: !cfg.verify_ssl })
    const idx = configs.value.findIndex((c) => c.source_name === cfg.source_name)
    if (idx >= 0) configs.value[idx] = updated
  } catch (e: any) {
    error.value = e.message || 'Failed to update'
  } finally {
    saving.value = null
  }
}

async function updateTopN(cfg: CrawlConfig, value: number) {
  if (value < 1 || value > 500) return
  saving.value = cfg.source_name
  try {
    const updated = await updateCrawlConfig(cfg.source_name, { top_n: value })
    const idx = configs.value.findIndex((c) => c.source_name === cfg.source_name)
    if (idx >= 0) configs.value[idx] = updated
  } catch (e: any) {
    error.value = e.message || 'Failed to update'
  } finally {
    saving.value = null
  }
}

function openAddDialog() {
  newSource.value = {
    source_name: '',
    enabled: true,
    top_n: 100,
    capture_summary: true,
    verify_ssl: true,
    feed_url: null,
  }
  addDialog.value = true
}

async function addSource() {
  addLoading.value = true
  error.value = null
  try {
    const created = await createCrawlConfig(newSource.value)
    configs.value.push(created)
    configs.value.sort((a, b) => a.source_name.localeCompare(b.source_name))
    addDialog.value = false
  } catch (e: any) {
    error.value = e.message || 'Failed to create source'
  } finally {
    addLoading.value = false
  }
}

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
    configs.value = configs.value.filter((c) => c.source_name !== deleteTarget.value)
    deleteDialog.value = false
  } catch (e: any) {
    error.value = e.message || 'Failed to delete source'
  } finally {
    deleteLoading.value = false
    deleteTarget.value = null
  }
}

function openEditDialog(cfg: CrawlConfig) {
  editSource.value = cfg
  editForm.value = {
    top_n: cfg.top_n,
    feed_url: cfg.feed_url,
    capture_summary: cfg.capture_summary,
    verify_ssl: cfg.verify_ssl,
    enabled: cfg.enabled,
  }
  editDialog.value = true
}

async function saveEdit() {
  if (!editSource.value) return
  editLoading.value = true
  error.value = null
  try {
    const updated = await updateCrawlConfig(editSource.value.source_name, {
      top_n: editForm.value.top_n,
      feed_url: editForm.value.feed_url,
      capture_summary: editForm.value.capture_summary,
      verify_ssl: editForm.value.verify_ssl,
      enabled: editForm.value.enabled,
    })
    const idx = configs.value.findIndex((c) => c.source_name === editSource.value!.source_name)
    if (idx >= 0) configs.value[idx] = updated
    editDialog.value = false
  } catch (e: any) {
    error.value = e.message || 'Failed to update source'
  } finally {
    editLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <v-container>
    <v-row>
      <v-col>
        <div class="d-flex align-center mb-4">
          <h1 class="text-h4">Sources</h1>
          <v-spacer />
          <v-btn color="primary" prepend-icon="mdi-plus" @click="openAddDialog">
            Add Source
          </v-btn>
        </div>

        <v-alert v-if="error" type="error" closable class="mb-4" @click:close="error = null">
          {{ error }}
        </v-alert>

        <v-card>
          <v-data-table
            :items="configs"
            :loading="loading"
            item-value="source_name"
            :headers="[
              { title: 'Source', key: 'source_name' },
              { title: 'Enabled', key: 'enabled', align: 'center' },
              { title: 'Top N', key: 'top_n', align: 'center' },
              { title: 'Verify SSL', key: 'verify_ssl', align: 'center' },
              { title: 'Capture Summary', key: 'capture_summary', align: 'center' },
              { title: 'Feed URL', key: 'feed_url' },
              { title: 'Updated', key: 'updated_at' },
              { title: '', key: 'actions', sortable: false, align: 'center' },
            ]"
            :items-per-page="-1"
            hide-default-footer
          >
            <template #item.enabled="{ item }">
              <v-switch
                :model-value="item.enabled"
                color="primary"
                hide-details
                density="compact"
                :loading="saving === item.source_name"
                @update:model-value="toggleEnabled(item)"
              />
            </template>

            <template #item.top_n="{ item }">
              <v-text-field
                :model-value="item.top_n"
                type="number"
                min="1"
                max="500"
                density="compact"
                hide-details
                style="max-width: 100px"
                :loading="saving === item.source_name"
                @change="(e: any) => updateTopN(item, Number(e.target?.value ?? item.top_n))"
                @keyup.enter="(e: any) => updateTopN(item, Number(e.target?.value ?? item.top_n))"
              />
            </template>

            <template #item.verify_ssl="{ item }">
              <v-switch
                :model-value="item.verify_ssl"
                color="success"
                hide-details
                density="compact"
                :loading="saving === item.source_name"
                @update:model-value="toggleVerifySsl(item)"
              />
            </template>

            <template #item.capture_summary="{ item }">
              <v-icon :color="item.capture_summary ? 'success' : 'grey'">
                {{ item.capture_summary ? 'mdi-check-circle' : 'mdi-close-circle' }}
              </v-icon>
            </template>

            <template #item.feed_url="{ item }">
              <span class="text-caption text-truncate" style="max-width: 300px; display: inline-block">
                {{ item.feed_url || '—' }}
              </span>
            </template>

            <template #item.updated_at="{ item }">
              {{ new Date(item.updated_at).toLocaleString() }}
            </template>

            <template #item.actions="{ item }">
              <v-btn
                icon="mdi-pencil"
                size="small"
                variant="text"
                color="primary"
                @click="openEditDialog(item)"
              />
              <v-btn
                icon="mdi-delete"
                size="small"
                variant="text"
                color="error"
                @click="confirmDelete(item.source_name)"
              />
            </template>
          </v-data-table>
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
            :disabled="!newSource.source_name"
            @click="addSource"
          >
            Add
          </v-btn>
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

    <!-- Edit Source Dialog -->
    <v-dialog v-model="editDialog" max-width="500">
      <v-card>
        <v-card-title>Edit Source: {{ editSource?.source_name }}</v-card-title>
        <v-card-text>
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
            label="Enabled"
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
  </v-container>
</template>
