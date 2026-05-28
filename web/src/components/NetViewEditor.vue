<script setup lang="ts">
// NetViewEditor — displays and edits the harmonization "Net View" annotation.
// Phase 10, plan 10-05 T06.

import { ref, watch } from 'vue'
import { putHarmonization, type HarmonizationNetView } from '@/api/harmonization'
import { formatRelative } from '@/lib/format'

const props = defineProps<{
  topicId: string
  netView: HarmonizationNetView | null
  canEdit: boolean
}>()

const emit = defineEmits<{
  saved: []
  deleted: []
}>()

const editing = ref(false)
const draft = ref('')
const saving = ref(false)
const saveError = ref<string | null>(null)

watch(
  () => props.netView,
  (nv) => {
    draft.value = nv?.text ?? ''
  },
  { immediate: true },
)

function startEdit() {
  draft.value = props.netView?.text ?? ''
  editing.value = true
  saveError.value = null
}

function cancelEdit() {
  editing.value = false
  saveError.value = null
}

async function save() {
  if (!draft.value.trim()) return
  saving.value = true
  saveError.value = null
  try {
    await putHarmonization(props.topicId, draft.value.trim())
    editing.value = false
    emit('saved')
  } catch (err) {
    saveError.value = (err as Error).message
  } finally {
    saving.value = false
  }
}

function confirmDelete() {
  emit('deleted')
}
</script>

<template>
  <v-card variant="outlined">
    <v-card-item>
      <v-card-title class="text-subtitle-1 d-flex align-center">
        <v-icon icon="mdi-text-box-check-outline" class="mr-2" />
        Net View
        <v-spacer />
        <v-btn
          v-if="canEdit && !editing && netView"
          icon="mdi-pencil"
          size="small"
          variant="text"
          @click="startEdit"
        />
        <v-btn
          v-if="canEdit && !editing && netView"
          icon="mdi-delete"
          size="small"
          variant="text"
          color="error"
          @click="confirmDelete"
        />
        <v-btn
          v-if="canEdit && !editing && !netView"
          size="small"
          variant="tonal"
          prepend-icon="mdi-plus"
          @click="startEdit"
        >
          Add Net View
        </v-btn>
      </v-card-title>
    </v-card-item>

    <v-card-text>
      <!-- Display mode -->
      <template v-if="!editing">
        <div v-if="netView" class="text-body-1" style="white-space: pre-wrap">{{ netView.text }}</div>
        <div v-else class="text-medium-emphasis text-body-2">
          No net view has been authored for this topic yet.
        </div>
        <div v-if="netView?.authored_by" class="text-caption text-medium-emphasis mt-2">
          By {{ netView.authored_by.username }} · {{ formatRelative(netView.updated_at) }}
        </div>
      </template>

      <!-- Edit mode -->
      <template v-if="editing">
        <v-textarea
          v-model="draft"
          label="Net View"
          variant="outlined"
          rows="4"
          auto-grow
          :disabled="saving"
          placeholder="Write a cross-department summary assessment…"
        />
        <v-alert
          v-if="saveError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-2"
          :text="saveError"
        />
        <div class="d-flex" style="gap: 8px">
          <v-btn
            color="primary"
            :loading="saving"
            :disabled="!draft.trim()"
            @click="save"
          >
            Save
          </v-btn>
          <v-btn variant="text" :disabled="saving" @click="cancelEdit">
            Cancel
          </v-btn>
        </div>
      </template>
    </v-card-text>
  </v-card>
</template>
