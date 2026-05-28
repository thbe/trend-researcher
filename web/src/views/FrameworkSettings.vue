<script setup lang="ts">
// FrameworkSettings — per-department assessment framework enable + default.
//
// Reads `frameworks.system` (catalog) + `frameworks.mine` (enabled-for-dept)
// from the Pinia store. Saves via `frameworks.updateMine({enabled, default})`.
//
// Constraint: the default framework MUST be in the enabled set. UI enforces
// this by disabling the default radio for unchecked frameworks.

import { computed, onMounted, ref, watch } from 'vue'

import { useFrameworksStore } from '@/stores/frameworks'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const frameworks = useFrameworksStore()

const activeDeptName = computed(() => session.activeDepartment?.name ?? '—')

// Local working copies (string[] of framework IDs).
const enabled = ref<string[]>([])
const defaultId = ref<string | null>(null)

const saving = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)

function syncFromStore() {
  enabled.value = frameworks.mine.map((f) => f.id)
  defaultId.value = frameworks.defaultId
}

async function load() {
  error.value = null
  try {
    await Promise.all([frameworks.loadSystem(), frameworks.loadMine()])
    syncFromStore()
  } catch (e: any) {
    error.value = e.message || 'Failed to load frameworks'
  }
}

// Keep local state in sync when active department changes (the parent layout
// triggers frameworks.loadMine() via session.switchDepartment).
watch(
  () => frameworks.loadedMineForDept,
  () => syncFromStore(),
)

// When the user unchecks the currently-default framework, demote the default
// to the first remaining enabled one (or null if none).
watch(enabled, (next) => {
  if (defaultId.value && !next.includes(defaultId.value)) {
    defaultId.value = next[0] ?? null
  }
})

const canSave = computed(
  () =>
    enabled.value.length > 0 &&
    defaultId.value !== null &&
    enabled.value.includes(defaultId.value),
)

async function save() {
  if (!canSave.value || !defaultId.value) return
  saving.value = true
  error.value = null
  success.value = null
  try {
    await frameworks.updateMine({
      enabled: enabled.value,
      default: defaultId.value,
    })
    syncFromStore()
    success.value = 'Framework settings saved'
  } catch (e: any) {
    error.value = e.message || 'Failed to save framework settings'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <v-container>
    <v-row>
      <v-col cols="12" md="10" lg="8">
        <h1 class="text-h4 mb-1">Frameworks</h1>
        <div class="text-subtitle-1 text-medium-emphasis mb-4">
          Frameworks for: <strong>{{ activeDeptName }}</strong>
        </div>

        <v-alert v-if="error" type="error" closable class="mb-4" @click:close="error = null">
          {{ error }}
        </v-alert>

        <v-alert v-if="success" type="success" closable class="mb-4" @click:close="success = null">
          {{ success }}
        </v-alert>

        <v-card :loading="frameworks.loading">
          <v-card-title>Enabled assessment frameworks</v-card-title>
          <v-card-subtitle>
            Choose which frameworks analysts in this department can run. Exactly one must be marked as default.
          </v-card-subtitle>

          <v-card-text>
            <v-table density="comfortable">
              <thead>
                <tr>
                  <th style="width: 80px">Enabled</th>
                  <th>Name</th>
                  <th>Description</th>
                  <th style="width: 100px">Default</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="fw in frameworks.system" :key="fw.id">
                  <td>
                    <v-checkbox
                      :model-value="enabled.includes(fw.id)"
                      hide-details
                      density="compact"
                      @update:model-value="
                        (v) => {
                          if (v) {
                            if (!enabled.includes(fw.id)) enabled = [...enabled, fw.id]
                          } else {
                            enabled = enabled.filter((id) => id !== fw.id)
                          }
                        }
                      "
                    />
                  </td>
                  <td class="font-weight-medium">{{ fw.name }}</td>
                  <td class="text-body-2 text-medium-emphasis">
                    {{ fw.description ?? '—' }}
                  </td>
                  <td>
                    <v-radio-group
                      :model-value="defaultId"
                      hide-details
                      density="compact"
                      @update:model-value="(v) => (defaultId = v)"
                    >
                      <v-radio :value="fw.id" :disabled="!enabled.includes(fw.id)" />
                    </v-radio-group>
                  </td>
                </tr>
              </tbody>
            </v-table>
          </v-card-text>

          <v-card-actions>
            <v-spacer />
            <v-btn :disabled="!canSave" :loading="saving" color="primary" @click="save">
              Save
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>
