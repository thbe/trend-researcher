<script setup lang="ts">
import { computed } from 'vue'
import type { BusinessCase } from '@/api/assessment'

const props = defineProps<{ case: BusinessCase }>()

// Prefer structured_output; fall back to denormalised top-level fields.
const so = computed(() => props.case.structured_output ?? {})

function pick<T = unknown>(key: string, fallback: T): T {
  const v = (so.value as Record<string, unknown>)[key]
  return (v ?? fallback) as T
}

const verdict = computed(() =>
  pick<string>('verdict', props.case.relevance_verdict ?? 'unknown'),
)
const reason = computed(() => pick<string>('reason', props.case.relevance_reason ?? ''))
const reasoning = computed(() => pick<string | null>('reasoning', null))
const category = computed(() =>
  pick<string | null>('category', props.case.category ?? null),
)
const importance = computed(() => pick<number | null>('importance', props.case.importance ?? null))
const investmentBand = computed(() =>
  pick<string | null>('investment_band', props.case.investment_band ?? null),
)
const confidence = computed(() =>
  pick<number | null>('confidence', props.case.confidence ?? null),
)

const verdictColor = computed(() =>
  verdict.value === 'relevant' ? 'success' : verdict.value === 'not-relevant' ? 'grey' : 'warning',
)
const categoryColor = computed(() => {
  switch (category.value) {
    case 'opportunity':
      return 'info'
    case 'risk':
      return 'error'
    case 'neutral':
      return 'grey'
    default:
      return undefined
  }
})
</script>

<template>
  <v-card variant="outlined">
    <v-card-item>
      <template #prepend>
        <v-chip :color="verdictColor" size="small" label>{{ verdict }}</v-chip>
      </template>
      <v-card-title class="text-subtitle-1">
        {{ case.framework?.name ?? 'Relevance Verdict' }}
      </v-card-title>
      <v-card-subtitle>
        {{ case.model_used }} · {{ case.prompt_version }}
      </v-card-subtitle>
      <template #append>
        <v-chip v-if="category" :color="categoryColor" size="small" variant="tonal" class="mr-2">
          {{ category }}
        </v-chip>
        <v-chip v-if="importance != null" size="small" variant="tonal" class="mr-2">
          Importance {{ importance }}
        </v-chip>
        <v-chip v-if="confidence != null" size="small" variant="tonal">
          Confidence {{ (confidence * 100).toFixed(0) }}%
        </v-chip>
      </template>
    </v-card-item>
    <v-card-text>
      <div class="text-body-2 mb-2">{{ reason }}</div>
      <v-expand-transition>
        <div v-if="reasoning" class="text-caption text-medium-emphasis">
          <v-divider class="my-2" />
          <strong>Reasoning:</strong> {{ reasoning }}
        </div>
      </v-expand-transition>
      <div v-if="investmentBand" class="mt-2">
        <v-chip size="x-small" variant="outlined">Investment: {{ investmentBand }}</v-chip>
      </div>
    </v-card-text>
  </v-card>
</template>
