<script setup lang="ts">
// SourceSubscriptions — per-department source on/off toggles.
//
// This view shows the GLOBAL source catalog (configured by superadmins in
// "Sources — Tech Config") and lets a dept_lead choose which sources their
// department subscribes to. The connector config (top_n, ssl, feed url) is
// read-only here — those are tech concerns.

import { computed, onMounted, ref } from 'vue'

import { listDepartmentSources, updateDepartmentSource, type DepartmentSource } from '@/api/departmentSources'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const activeDeptName = computed(() => session.activeDepartment?.name ?? '—')

const sources = ref<DepartmentSource[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)
// Per-row saving flags so toggling one row doesn't spinner the whole page.
const saving = ref<Record<string, boolean>>({})

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
    const body = await listDepartmentSources()
    sources.value = body.sources
  } catch (e: any) {
    error.value = e.message || 'Failed to load source subscriptions'
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
    // Sync with server response in case the API normalised any fields.
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

onMounted(load)
</script>

<template>
  <div>
    <div class="d-flex align-end mb-4">
      <div>
        <h1 class="text-h5 font-weight-medium">Source Subscriptions</h1>
        <div class="text-caption text-medium-emphasis mt-1">
          Choose which sources feed the topic list for <strong>{{ activeDeptName }}</strong>.
          Owned sources are always on; subscribed sources can be toggled anytime.
        </div>
      </div>
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
        Ask a superadmin to add sources in <em>Sources — Tech Config</em>.
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
          <v-card-text class="pt-3">
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
        </v-card>
      </v-col>
    </v-row>
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
