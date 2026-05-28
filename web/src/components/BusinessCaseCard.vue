<script setup lang="ts">
// Dispatcher: routes a BusinessCase to the framework-specific card component
// based on `case.framework.display_component`. Unknown components render a
// generic JSON fallback (with a console warning).
import { computed, defineAsyncComponent, type Component } from 'vue'
import type { BusinessCase } from '@/api/assessment'

const props = defineProps<{ case: BusinessCase }>()

const cardRegistry: Record<string, Component> = {
  VerdictCard: defineAsyncComponent(() => import('@/components/cards/VerdictCard.vue')),
  SwotCard: defineAsyncComponent(() => import('@/components/cards/SwotCard.vue')),
  PestleCard: defineAsyncComponent(() => import('@/components/cards/PestleCard.vue')),
}

const componentName = computed(
  () => props.case.framework?.display_component ?? 'VerdictCard',
)

const resolved = computed<Component | null>(() => {
  const c = cardRegistry[componentName.value]
  if (!c) {
    // eslint-disable-next-line no-console
    console.warn(
      `BusinessCaseCard: unknown display_component "${componentName.value}", ` +
        'rendering JSON fallback.',
    )
    return null
  }
  return c
})

const rawJson = computed(() => JSON.stringify(props.case.structured_output ?? {}, null, 2))
</script>

<template>
  <component :is="resolved" v-if="resolved" :case="case" />
  <v-card v-else variant="outlined">
    <v-card-item>
      <v-card-title class="text-subtitle-1">
        Unknown framework: {{ componentName }}
      </v-card-title>
      <v-card-subtitle>{{ case.model_used }} · {{ case.prompt_version }}</v-card-subtitle>
    </v-card-item>
    <v-card-text>
      <v-expansion-panels>
        <v-expansion-panel title="Raw structured output">
          <template #text>
            <pre class="text-caption" style="white-space: pre-wrap">{{ rawJson }}</pre>
          </template>
        </v-expansion-panel>
      </v-expansion-panels>
    </v-card-text>
  </v-card>
</template>
