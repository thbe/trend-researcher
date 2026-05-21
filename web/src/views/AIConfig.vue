<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getAIConfig, updateAIConfig, listAvailableModels, type AIConfig } from '@/api/aiConfig'

const config = ref<AIConfig | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)

// Form fields
const form = ref({ base_url: '', model: '', api_token: '', business_context: '', thinking_effort: 'off' })

// Available models from provider
const availableModels = ref<string[]>([])
const modelsLoading = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    config.value = await getAIConfig()
    form.value = {
      base_url: config.value.base_url,
      model: config.value.model,
      api_token: config.value.api_token ?? '',
      business_context: config.value.business_context ?? '',
      thinking_effort: config.value.thinking_effort ?? 'off',
    }
    await fetchModels()
  } catch (e: any) {
    error.value = e.message || 'Failed to load AI config'
  } finally {
    loading.value = false
  }
}

async function fetchModels() {
  modelsLoading.value = true
  try {
    const models = await listAvailableModels()
    availableModels.value = models.map((m) => m.name)
  } catch {
    // Silently fail — user can still type manually
    availableModels.value = []
  } finally {
    modelsLoading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = null
  success.value = null
  try {
    config.value = await updateAIConfig({
      base_url: form.value.base_url,
      model: form.value.model,
      api_token: form.value.api_token || null,
      business_context: form.value.business_context || null,
      thinking_effort: form.value.thinking_effort,
    })
    form.value = {
      base_url: config.value.base_url,
      model: config.value.model,
      api_token: config.value.api_token ?? '',
      business_context: config.value.business_context ?? '',
      thinking_effort: config.value.thinking_effort ?? 'off',
    }
    success.value = 'AI configuration saved successfully'
  } catch (e: any) {
    error.value = e.message || 'Failed to save AI config'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <v-container>
    <v-row>
      <v-col cols="12" md="8" lg="6">
        <h1 class="text-h4 mb-4">AI Configuration</h1>

        <v-alert v-if="error" type="error" closable class="mb-4" @click:close="error = null">
          {{ error }}
        </v-alert>

        <v-alert v-if="success" type="success" closable class="mb-4" @click:close="success = null">
          {{ success }}
        </v-alert>

        <v-card :loading="loading">
          <v-card-text>
            <v-text-field
              v-model="form.base_url"
              label="Base URL"
              hint="Ollama or OpenAI-compatible API endpoint"
              persistent-hint
              class="mb-4"
              prepend-icon="mdi-web"
            />

            <v-combobox
              v-model="form.model"
              :items="availableModels"
              :loading="modelsLoading"
              label="Model"
              hint="Models available on the provider — or type a custom name"
              persistent-hint
              class="mb-4"
              prepend-icon="mdi-brain"
            >
              <template #append>
                <v-btn icon="mdi-refresh" size="small" variant="text" :loading="modelsLoading" @click="fetchModels" />
              </template>
            </v-combobox>

            <v-text-field
              v-model="form.api_token"
              label="API Token"
              hint="Optional — leave empty for local Ollama"
              persistent-hint
              type="password"
              prepend-icon="mdi-key"
              class="mb-4"
            />

            <v-textarea
              v-model="form.business_context"
              label="Business Context"
              hint="Describe your business so the AI can judge relevance. What counts as an opportunity? What counts as a risk?"
              persistent-hint
              rows="6"
              auto-grow
              prepend-icon="mdi-domain"
              class="mb-4"
            />

            <v-select
              v-model="form.thinking_effort"
              :items="[
                { title: 'Off — fastest, no reasoning', value: 'off' },
                { title: 'Low — brief reasoning', value: 'low' },
                { title: 'Medium — moderate reasoning', value: 'medium' },
                { title: 'High — deep reasoning', value: 'high' },
              ]"
              label="Thinking Effort"
              hint="Controls how much reasoning the model does before answering. Higher = better but slower."
              persistent-hint
              prepend-icon="mdi-head-cog-outline"
            />
          </v-card-text>

          <v-card-actions>
            <v-spacer />
            <v-btn color="primary" :loading="saving" :disabled="loading" @click="save">
              Save Configuration
            </v-btn>
          </v-card-actions>
        </v-card>

        <v-card class="mt-4" variant="outlined" v-if="availableModels.length > 0">
          <v-card-title class="text-subtitle-1">
            <v-icon start>mdi-information-outline</v-icon>
            Available Models ({{ availableModels.length }})
          </v-card-title>
          <v-card-text>
            <v-chip v-for="m in availableModels" :key="m" class="ma-1" size="small" @click="form.model = m">
              {{ m }}
            </v-chip>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>
