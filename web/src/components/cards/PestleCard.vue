<script setup lang="ts">
import { computed } from 'vue'
import type { BusinessCase } from '@/api/assessment'

const props = defineProps<{ case: BusinessCase }>()

interface PestleCell {
  relevance: 'low' | 'med' | 'high'
  notes: string
}

const so = computed(() => props.case.structured_output ?? {})

type PestleKey = 'political' | 'economic' | 'social' | 'technological' | 'legal' | 'environmental'

function cell(key: PestleKey): PestleCell {
  const v = (so.value as Record<string, unknown>)[key] as PestleCell | undefined
  return v ?? { relevance: 'low', notes: '' }
}

const cells = computed<Record<PestleKey, PestleCell>>(() => ({
  political: cell('political'),
  economic: cell('economic'),
  social: cell('social'),
  technological: cell('technological'),
  legal: cell('legal'),
  environmental: cell('environmental'),
}))

const verdict = computed(
  () => ((so.value as any).verdict as string) ?? props.case.relevance_verdict ?? 'unknown',
)
const importance = computed(
  () => ((so.value as any).importance as number | null) ?? props.case.importance ?? null,
)
const confidence = computed(
  () => ((so.value as any).confidence as number | null) ?? props.case.confidence ?? null,
)
const reason = computed(
  () => ((so.value as any).reason as string) ?? props.case.relevance_reason ?? '',
)

const verdictColor = computed(() => (verdict.value === 'relevant' ? 'success' : 'grey'))

const dimensions: { key: PestleKey; label: string; icon: string }[] = [
  { key: 'political', label: 'Political', icon: 'mdi-bank-outline' },
  { key: 'economic', label: 'Economic', icon: 'mdi-chart-line' },
  { key: 'social', label: 'Social', icon: 'mdi-account-group-outline' },
  { key: 'technological', label: 'Technological', icon: 'mdi-chip' },
  { key: 'legal', label: 'Legal', icon: 'mdi-gavel' },
  { key: 'environmental', label: 'Environmental', icon: 'mdi-leaf' },
]

function relevanceColor(r: PestleCell['relevance']): string {
  return r === 'high' ? 'error' : r === 'med' ? 'warning' : 'grey'
}
</script>

<template>
  <v-card variant="outlined">
    <v-card-item>
      <template #prepend>
        <v-chip :color="verdictColor" size="small" label>{{ verdict }}</v-chip>
      </template>
      <v-card-title class="text-subtitle-1">
        {{ case.framework?.name ?? 'PESTLE' }}
      </v-card-title>
      <v-card-subtitle>{{ case.model_used }} · {{ case.prompt_version }}</v-card-subtitle>
      <template #append>
        <v-chip v-if="importance != null" size="small" variant="tonal" class="mr-2">
          Importance {{ importance }}
        </v-chip>
        <v-chip v-if="confidence != null" size="small" variant="tonal">
          Confidence {{ (confidence * 100).toFixed(0) }}%
        </v-chip>
      </template>
    </v-card-item>
    <v-card-text>
      <div v-if="reason" class="text-body-2 mb-3">{{ reason }}</div>
      <v-row dense>
        <v-col v-for="d in dimensions" :key="d.key" cols="12" md="6" lg="4">
          <v-card variant="tonal" class="h-100">
            <v-card-item density="compact">
              <template #prepend><v-icon :icon="d.icon" /></template>
              <v-card-title class="text-body-1">{{ d.label }}</v-card-title>
              <template #append>
                <v-chip :color="relevanceColor(cells[d.key].relevance)" size="x-small" label>
                  {{ cells[d.key].relevance }}
                </v-chip>
              </template>
            </v-card-item>
            <v-card-text class="pt-0 text-body-2" style="white-space: pre-wrap">
              {{ cells[d.key].notes || '—' }}
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </v-card-text>
  </v-card>
</template>
