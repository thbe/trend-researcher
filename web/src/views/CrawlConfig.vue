<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listCrawlConfig, updateCrawlConfig, type CrawlConfig } from '@/api/crawlConfig'

const configs = ref<CrawlConfig[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const saving = ref<string | null>(null)

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

onMounted(load)
</script>

<template>
  <v-container>
    <v-row>
      <v-col>
        <h1 class="text-h4 mb-4">Crawl Configuration</h1>

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
              { title: 'Capture Summary', key: 'capture_summary', align: 'center' },
              { title: 'Feed URL', key: 'feed_url' },
              { title: 'Updated', key: 'updated_at' },
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
          </v-data-table>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>
