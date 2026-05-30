<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getAIConfig, updateAIConfig, listAvailableModels, type AIConfig, type AIProvider } from '@/api/aiConfig'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const activeDeptName = computed(() => session.activeDepartment?.name ?? '—')

const config = ref<AIConfig | null>(null)
const loading = ref(false)
const saving = ref(false)
const initializing = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)

// Empty-state flag: backend returned 404 (no AI config row yet for this dept).
const isEmpty = ref(false)

// Form fields
const form = ref({
  provider: 'ollama' as AIProvider,
  base_url: '',
  model: '',
  api_token: '',
  business_context: '',
  opportunity_criteria: '',
  risk_criteria: '',
  thinking_effort: 'off',
  request_timeout_seconds: 120,
})

// Provider catalogue — drives the dropdown + hint text. Keep in sync with
// the backend ``provider`` enum (assessment.py / migration 0023).
const providerOptions = [
  { title: 'Ollama — local /api/chat (no /v1 suffix)', value: 'ollama' },
  { title: 'OpenAI-compatible — /v1 endpoint (oMLX, LM Studio, vLLM, OpenAI)', value: 'openai' },
  { title: 'Anthropic — hosted Claude', value: 'anthropic' },
]

const baseUrlHint = computed(() => {
  switch (form.value.provider) {
    case 'openai':
      return 'OpenAI-compatible /v1 root, e.g. http://host.docker.internal:8000/v1 for oMLX'
    case 'anthropic':
      return 'Anthropic API base, usually https://api.anthropic.com'
    default:
      return 'Ollama base URL, e.g. http://ollama:11434 inside the Compose network'
  }
})

// Available models from provider
const availableModels = ref<string[]>([])
const modelsLoading = ref(false)

function applyConfig(cfg: AIConfig) {
  config.value = cfg
  form.value = {
    provider: cfg.provider,
    base_url: cfg.base_url,
    model: cfg.model,
    api_token: cfg.api_token ?? '',
    business_context: cfg.business_context ?? '',
    opportunity_criteria: cfg.opportunity_criteria ?? '',
    risk_criteria: cfg.risk_criteria ?? '',
    thinking_effort: cfg.thinking_effort ?? 'off',
    request_timeout_seconds: cfg.request_timeout_seconds ?? 120,
  }
}

async function load() {
  loading.value = true
  error.value = null
  isEmpty.value = false
  try {
    const cfg = await getAIConfig()
    if (cfg === null) {
      isEmpty.value = true
      config.value = null
    } else {
      applyConfig(cfg)
    }
    await fetchModels()
  } catch (e: any) {
    error.value = e.message || 'Failed to load AI config'
  } finally {
    loading.value = false
  }
}

async function initialize() {
  // Seed an initial AI config row for the active department with minimal
  // defaults. User can edit + save afterwards.
  initializing.value = true
  error.value = null
  try {
    const cfg = await updateAIConfig({
      provider: 'ollama',
      base_url: 'http://localhost:11434',
      model: 'llama3',
      thinking_effort: 'off',
      request_timeout_seconds: 120,
    })
    applyConfig(cfg)
    isEmpty.value = false
    success.value = 'AI configuration initialized — edit and save when ready'
    await fetchModels()
  } catch (e: any) {
    error.value = e.message || 'Failed to initialize AI config'
  } finally {
    initializing.value = false
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
    const cfg = await updateAIConfig({
      provider: form.value.provider,
      base_url: form.value.base_url,
      model: form.value.model,
      api_token: form.value.api_token || null,
      business_context: form.value.business_context || null,
      opportunity_criteria: form.value.opportunity_criteria || null,
      risk_criteria: form.value.risk_criteria || null,
      thinking_effort: form.value.thinking_effort,
      request_timeout_seconds: form.value.request_timeout_seconds,
    })
    applyConfig(cfg)
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
        <h1 class="text-h4 mb-1">AI Configuration</h1>
        <div class="text-subtitle-1 text-medium-emphasis mb-4">
          Configuring AI for: <strong>{{ activeDeptName }}</strong>
        </div>

        <v-alert v-if="error" type="error" closable class="mb-4" @click:close="error = null">
          {{ error }}
        </v-alert>

        <v-alert v-if="success" type="success" closable class="mb-4" @click:close="success = null">
          {{ success }}
        </v-alert>

        <v-card v-if="isEmpty" class="mb-4" variant="outlined">
          <v-card-text class="text-center pa-8">
            <v-icon size="64" color="grey-lighten-1" class="mb-4">mdi-robot-outline</v-icon>
            <h2 class="text-h6 mb-2">No AI configuration yet</h2>
            <p class="text-body-2 text-medium-emphasis mb-4">
              The <strong>{{ activeDeptName }}</strong> department doesn't have AI settings yet.
              Initialize with sensible defaults — you can edit and save afterwards.
            </p>
            <v-btn color="primary" variant="flat" :loading="initializing" @click="initialize">
              <v-icon start>mdi-rocket-launch-outline</v-icon>
              Initialize AI Configuration
            </v-btn>
          </v-card-text>
        </v-card>

        <template v-else>
          <!-- Section 1: Provider connection -->
          <v-card class="mb-4" :loading="loading">
            <v-card-item>
              <template #prepend>
                <v-icon icon="mdi-server-network" color="secondary" />
              </template>
              <v-card-title class="text-subtitle-1 font-weight-medium">Provider Connection</v-card-title>
              <v-card-subtitle>Where the LLM lives</v-card-subtitle>
            </v-card-item>
            <v-card-text>
              <v-select
                v-model="form.provider"
                :items="providerOptions"
                label="Provider"
                hint="Picks the adapter explicitly — no URL sniffing."
                persistent-hint
                class="mb-3"
                prepend-inner-icon="mdi-chip"
              />
              <v-text-field
                v-model="form.base_url"
                label="Base URL"
                :hint="baseUrlHint"
                persistent-hint
                class="mb-3"
                prepend-inner-icon="mdi-web"
              />
              <v-combobox
                v-model="form.model"
                :items="availableModels"
                :loading="modelsLoading"
                label="Model"
                hint="Models available on the provider — or type a custom name"
                persistent-hint
                class="mb-3"
                prepend-inner-icon="mdi-brain"
              >
                <template #append-inner>
                  <v-btn
                    icon="mdi-refresh"
                    size="small"
                    variant="text"
                    :loading="modelsLoading"
                    @click.stop="fetchModels"
                  />
                </template>
              </v-combobox>
              <v-text-field
                v-model="form.api_token"
                label="API Token"
                hint="Optional — leave empty for local Ollama"
                persistent-hint
                type="password"
                prepend-inner-icon="mdi-key"
              />
            </v-card-text>
          </v-card>

          <!-- Section 2: Assessment criteria -->
          <v-card class="mb-4">
            <v-card-item>
              <template #prepend>
                <v-icon icon="mdi-clipboard-text-outline" color="secondary" />
              </template>
              <v-card-title class="text-subtitle-1 font-weight-medium">Assessment Criteria</v-card-title>
              <v-card-subtitle>Tell the AI what matters for {{ activeDeptName }}</v-card-subtitle>
            </v-card-item>
            <v-card-text>
              <v-textarea
                v-model="form.business_context"
                label="Business Context"
                hint="Who you are: industry, geography, channels, scale. The AI uses this to interpret your criteria below."
                persistent-hint
                rows="4"
                auto-grow
                prepend-inner-icon="mdi-domain"
                class="mb-3"
              />
              <v-textarea
                v-model="form.opportunity_criteria"
                label="Opportunity Criteria"
                hint="What counts as an OPPORTUNITY? List concrete signals (one per line)."
                persistent-hint
                rows="5"
                auto-grow
                prepend-inner-icon="mdi-trending-up"
                class="mb-3"
              />
              <v-textarea
                v-model="form.risk_criteria"
                label="Risk Criteria"
                hint="What counts as a RISK? List concrete threats (one per line)."
                persistent-hint
                rows="5"
                auto-grow
                prepend-inner-icon="mdi-alert-octagon-outline"
              />
            </v-card-text>
          </v-card>

          <!-- Section 3: Runtime tuning -->
          <v-card class="mb-4">
            <v-card-item>
              <template #prepend>
                <v-icon icon="mdi-tune-variant" color="secondary" />
              </template>
              <v-card-title class="text-subtitle-1 font-weight-medium">Runtime Tuning</v-card-title>
              <v-card-subtitle>How hard the model thinks, how long you wait</v-card-subtitle>
            </v-card-item>
            <v-card-text>
              <v-select
                v-model="form.thinking_effort"
                :items="[
                  { title: 'Off — fastest, no reasoning', value: 'off' },
                  { title: 'Low — brief reasoning', value: 'low' },
                  { title: 'Medium — moderate reasoning', value: 'medium' },
                  { title: 'High — deep reasoning', value: 'high' },
                ]"
                label="Thinking Effort"
                hint="Higher = better but slower."
                persistent-hint
                prepend-inner-icon="mdi-head-cog-outline"
                class="mb-3"
              />
              <v-text-field
                v-model.number="form.request_timeout_seconds"
                type="number"
                min="10"
                max="3600"
                label="Request Timeout (seconds)"
                hint="Per-LLM-request timeout. Raise for slow local models (300–600). Default: 120."
                persistent-hint
                prepend-inner-icon="mdi-timer-outline"
              />
            </v-card-text>
          </v-card>

          <!-- Sticky save bar -->
          <div
            class="d-flex align-center pa-3 mb-4 rounded-lg"
            style="position: sticky; bottom: 16px; background: rgb(var(--v-theme-surface)); box-shadow: 0 -2px 8px rgba(0,0,0,0.08); z-index: 2;"
          >
            <span class="text-caption text-medium-emphasis">
              Changes save to <strong>{{ activeDeptName }}</strong>
            </span>
            <v-spacer />
            <v-btn
              color="primary"
              variant="flat"
              size="large"
              prepend-icon="mdi-content-save-outline"
              :loading="saving"
              :disabled="loading"
              @click="save"
            >
              Save Configuration
            </v-btn>
          </div>
        </template>

        <v-card class="mt-4" variant="outlined" v-if="!isEmpty && availableModels.length > 0">
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
