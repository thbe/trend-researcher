<script setup lang="ts">
// FrameworkPicker — v-select bound to a framework id, sourced from the
// active dept's enabled set in the frameworks store. Auto-defaults to the
// dept's default framework when modelValue is null.
import { computed, onMounted, watch } from 'vue'
import { useFrameworksStore } from '@/stores/frameworks'

const props = defineProps<{
  modelValue: string | null
  disabled?: boolean
  label?: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: string | null): void
}>()

const frameworks = useFrameworksStore()

const items = computed(() =>
  frameworks.mine.map((f) => ({ title: f.name, value: f.id })),
)

const value = computed({
  get: () => props.modelValue,
  set: (v: string | null) => emit('update:modelValue', v),
})

onMounted(async () => {
  if (frameworks.mine.length === 0) await frameworks.loadMine()
  applyDefaultIfNeeded()
})

watch(
  () => frameworks.defaultId,
  () => applyDefaultIfNeeded(),
)

function applyDefaultIfNeeded() {
  if (props.modelValue) return
  const def = frameworks.defaultId
  if (def) emit('update:modelValue', def)
}
</script>

<template>
  <v-select
    v-model="value"
    :items="items"
    item-title="title"
    item-value="value"
    :label="label ?? 'Framework'"
    :disabled="disabled || items.length === 0"
    :loading="frameworks.loading"
    density="comfortable"
    variant="outlined"
    hide-details
  />
</template>
