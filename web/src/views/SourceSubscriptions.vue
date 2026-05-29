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

onMounted(load)
</script>

<template>
  <v-container>
    <v-row>
      <v-col cols="12" md="10" lg="8">
        <h1 class="text-h4 mb-1">Source Subscriptions</h1>
        <div class="text-subtitle-1 text-medium-emphasis mb-4">
          Sources for: <strong>{{ activeDeptName }}</strong>
        </div>

        <v-alert v-if="error" type="error" closable class="mb-4" @click:close="error = null">
          {{ error }}
        </v-alert>

        <v-alert v-if="success" type="success" closable class="mb-4" @click:close="success = null">
          {{ success }}
        </v-alert>

        <v-card :loading="loading">
          <v-card-text v-if="!loading && sources.length === 0" class="text-center pa-8">
            <v-icon size="48" color="grey-lighten-1" class="mb-2">mdi-rss-off</v-icon>
            <p class="text-body-2 text-medium-emphasis">
              No sources available. Ask a superadmin to add sources in
              <em>Sources — Tech Config</em>.
            </p>
          </v-card-text>

          <v-list v-else lines="two">
            <template v-for="(src, idx) in sources" :key="src.source_name">
              <v-divider v-if="idx > 0" />
              <v-list-item>
                <template #prepend>
                  <v-icon>mdi-rss</v-icon>
                </template>

                <v-list-item-title class="text-body-1 font-weight-medium">
                  {{ src.source_name }}
                  <v-chip
                    v-if="src.owned"
                    size="x-small"
                    color="primary"
                    variant="tonal"
                    class="ml-2"
                  >
                    Owned
                  </v-chip>
                </v-list-item-title>
                <v-list-item-subtitle>
                  Owner: <strong>{{ src.owner_department_name }}</strong> ·
                  top_n: {{ src.top_n }} ·
                  <span v-if="src.feed_url">{{ src.feed_url }}</span>
                  <span v-else class="text-disabled">no feed url</span>
                </v-list-item-subtitle>

                <template #append>
                  <v-tooltip
                    v-if="src.owned"
                    text="Your department owns this source — it is always active and cannot be unsubscribed here."
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
                    @update:model-value="(v) => toggle(src, v === true)"
                  />
                </template>
              </v-list-item>
            </template>
          </v-list>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>
