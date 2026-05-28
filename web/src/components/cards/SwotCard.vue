<script setup lang="ts">
import { computed } from 'vue'
import type { BusinessCase } from '@/api/assessment'

const props = defineProps<{ bcase: BusinessCase }>()

interface SwotEntry {
  point: string
  rationale: string
}

const so = computed(() => props.bcase.structured_output ?? {})

function cell(key: 'strengths' | 'weaknesses' | 'opportunities' | 'threats'): SwotEntry[] {
  const v = (so.value as Record<string, unknown>)[key]
  return Array.isArray(v) ? (v as SwotEntry[]) : []
}

const strengths = computed(() => cell('strengths'))
const weaknesses = computed(() => cell('weaknesses'))
const opportunities = computed(() => cell('opportunities'))
const threats = computed(() => cell('threats'))

const verdict = computed(
  () => ((so.value as any).verdict as string) ?? props.bcase.relevance_verdict ?? 'unknown',
)
const importance = computed(
  () => ((so.value as any).importance as number | null) ?? props.bcase.importance ?? null,
)
const confidence = computed(
  () => ((so.value as any).confidence as number | null) ?? props.bcase.confidence ?? null,
)
const reason = computed(
  () => ((so.value as any).reason as string) ?? props.bcase.relevance_reason ?? '',
)

const verdictColor = computed(() =>
  verdict.value === 'relevant' ? 'success' : 'grey',
)

const quadrants: {
  key: 'strengths' | 'weaknesses' | 'opportunities' | 'threats'
  label: string
  color: string
  icon: string
}[] = [
  { key: 'strengths', label: 'Strengths', color: 'success', icon: 'mdi-arm-flex-outline' },
  { key: 'weaknesses', label: 'Weaknesses', color: 'warning', icon: 'mdi-alert-circle-outline' },
  { key: 'opportunities', label: 'Opportunities', color: 'info', icon: 'mdi-lightbulb-outline' },
  { key: 'threats', label: 'Threats', color: 'error', icon: 'mdi-shield-alert-outline' },
]

const cellsByKey = computed(() => ({
  strengths: strengths.value,
  weaknesses: weaknesses.value,
  opportunities: opportunities.value,
  threats: threats.value,
}))
</script>

<template>
  <v-card variant="outlined">
    <v-card-item>
      <template #prepend>
        <v-chip :color="verdictColor" size="small" label>{{ verdict }}</v-chip>
      </template>
      <v-card-title class="text-subtitle-1">
        {{ bcase.framework?.name ?? 'SWOT' }}
      </v-card-title>
      <v-card-subtitle>{{ bcase.model_used }} · {{ bcase.prompt_version }}</v-card-subtitle>
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
        <v-col v-for="q in quadrants" :key="q.key" cols="12" md="6">
          <v-card :color="q.color" variant="tonal" class="h-100">
            <v-card-item density="compact">
              <template #prepend><v-icon :icon="q.icon" /></template>
              <v-card-title class="text-body-1">{{ q.label }}</v-card-title>
            </v-card-item>
            <v-card-text class="pt-0">
              <v-list
                v-if="cellsByKey[q.key].length"
                bg-color="transparent"
                density="compact"
                class="pa-0"
              >
                <v-list-item v-for="(entry, i) in cellsByKey[q.key]" :key="i" class="pl-0">
                  <v-list-item-title class="text-body-2 font-weight-medium">
                    {{ entry.point }}
                  </v-list-item-title>
                  <v-list-item-subtitle class="text-caption" style="white-space: normal">
                    {{ entry.rationale }}
                  </v-list-item-subtitle>
                </v-list-item>
              </v-list>
              <div v-else class="text-caption text-medium-emphasis">— none —</div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </v-card-text>
  </v-card>
</template>
