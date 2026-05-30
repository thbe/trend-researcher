<script setup lang="ts">
// Departments — superadmin list + CRUD.
//
// Backed by /api/departments (list/create/update/delete). Clicking a row
// drills into per-dept settings (members) at /departments/:id/settings.
// The 'default' department cannot be deleted (backend returns 409); we
// hide the delete action for it as a UX courtesy.

import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createDepartment,
  deleteDepartment,
  listDepartments,
  updateDepartment,
  type Department,
} from '@/api/departments'

import { useSessionStore } from '@/stores/session'

const session = useSessionStore()

const router = useRouter()

const departments = ref<Department[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)

// Create dialog state
const createDialog = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', slug: '', description: '' })

// Rename dialog state
const renameDialog = ref(false)
const renaming = ref(false)
const renameTarget = ref<Department | null>(null)
const renameForm = ref({ name: '', description: '' })

// Delete confirm dialog state
const deleteDialog = ref(false)
const deleting = ref(false)
const deleteTarget = ref<Department | null>(null)

const headers = [
  { title: 'Name', key: 'name' },
  { title: 'Slug', key: 'slug' },
  { title: 'Description', key: 'description' },
  { title: 'Created', key: 'created_at' },
  { title: 'Actions', key: 'actions', sortable: false, align: 'end' as const },
]

async function load() {
  loading.value = true
  error.value = null
  try {
    const body = await listDepartments()
    departments.value = body.departments
  } catch (e: any) {
    error.value = e.message || 'Failed to load departments'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createForm.value = { name: '', slug: '', description: '' }
  createDialog.value = true
}

async function doCreate() {
  creating.value = true
  error.value = null
  try {
    await createDepartment({
      name: createForm.value.name.trim(),
      slug: createForm.value.slug.trim(),
      description: createForm.value.description.trim() || null,
    })
    success.value = `Department "${createForm.value.name}" created`
    createDialog.value = false
    await load()
    // Superadmin's session payload includes ALL departments — refresh so
    // the new dept shows up in the AppBar switcher right away.
    await session.refresh()
  } catch (e: any) {
    error.value = e.message || 'Failed to create department'
  } finally {
    creating.value = false
  }
}

function openRename(dept: Department) {
  renameTarget.value = dept
  renameForm.value = { name: dept.name, description: dept.description ?? '' }
  renameDialog.value = true
}

async function doRename() {
  if (!renameTarget.value) return
  renaming.value = true
  error.value = null
  try {
    await updateDepartment(renameTarget.value.id, {
      name: renameForm.value.name.trim(),
      description: renameForm.value.description.trim() || null,
    })
    success.value = 'Department updated'
    renameDialog.value = false
    await load()
  } catch (e: any) {
    error.value = e.message || 'Failed to update department'
  } finally {
    renaming.value = false
  }
}

function openDelete(dept: Department) {
  deleteTarget.value = dept
  deleteDialog.value = true
}

async function doDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  error.value = null
  try {
    await deleteDepartment(deleteTarget.value.id)
    success.value = `Department "${deleteTarget.value.name}" deleted`
    deleteDialog.value = false
    await load()
    await session.refresh()
  } catch (e: any) {
    // 409 → last default dept or other backend constraint
    error.value = e.message || 'Failed to delete department'
  } finally {
    deleting.value = false
  }
}

function openSettings(dept: Department) {
  router.push(`/departments/${dept.id}/settings`)
}

function onRowClick(_e: unknown, payload: { item: Department }) {
  openSettings(payload.item)
}

onMounted(load)
</script>

<template>
  <v-container>
    <v-row>
      <v-col>
        <div class="d-flex align-center mb-4">
          <h1 class="text-h4">Departments</h1>
          <v-spacer />
          <v-btn color="primary" prepend-icon="mdi-plus" @click="openCreate">
            New Department
          </v-btn>
        </div>

        <v-alert v-if="error" type="error" closable class="mb-4" @click:close="error = null">
          {{ error }}
        </v-alert>

        <v-alert v-if="success" type="success" closable class="mb-4" @click:close="success = null">
          {{ success }}
        </v-alert>

        <v-card>
          <v-data-table
            :headers="headers"
            :items="departments"
            :loading="loading"
            item-value="id"
            hover
            @click:row="onRowClick"
          >
            <template #item.description="{ item }">
              <span v-if="item.description" class="text-body-2">{{ item.description }}</span>
              <span v-else class="text-disabled">—</span>
            </template>

            <template #item.created_at="{ item }">
              {{ new Date(item.created_at).toLocaleDateString() }}
            </template>

            <template #item.actions="{ item }">
              <v-btn
                icon="mdi-account-multiple"
                size="small"
                variant="text"
                title="Members & settings"
                @click.stop="openSettings(item)"
              />
              <v-btn
                icon="mdi-pencil"
                size="small"
                variant="text"
                title="Rename"
                @click.stop="openRename(item)"
              />
              <v-btn
                v-if="item.slug !== 'default'"
                icon="mdi-delete"
                size="small"
                variant="text"
                color="error"
                title="Delete"
                @click.stop="openDelete(item)"
              />
            </template>
          </v-data-table>
        </v-card>
      </v-col>
    </v-row>

    <!-- Create dialog -->
    <v-dialog v-model="createDialog" max-width="500">
      <v-card>
        <v-card-title>New Department</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="createForm.name"
            label="Name"
            hint="Human-readable name (e.g. Marketing)"
            persistent-hint
            class="mb-2"
          />
          <v-text-field
            v-model="createForm.slug"
            label="Slug"
            hint="Lowercase, hyphenated identifier (e.g. marketing)"
            persistent-hint
            class="mb-2"
          />
          <v-textarea
            v-model="createForm.description"
            label="Description (optional)"
            rows="2"
            auto-grow
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="createDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            :loading="creating"
            :disabled="!createForm.name.trim() || !createForm.slug.trim()"
            @click="doCreate"
          >
            Create
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Rename dialog -->
    <v-dialog v-model="renameDialog" max-width="500">
      <v-card>
        <v-card-title>Edit Department</v-card-title>
        <v-card-text>
          <v-text-field v-model="renameForm.name" label="Name" class="mb-2" />
          <v-textarea
            v-model="renameForm.description"
            label="Description"
            rows="2"
            auto-grow
          />
          <p class="text-caption text-medium-emphasis mt-2">
            Slug cannot be changed.
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="renameDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            :loading="renaming"
            :disabled="!renameForm.name.trim()"
            @click="doRename"
          >
            Save
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete confirm dialog -->
    <v-dialog v-model="deleteDialog" max-width="450">
      <v-card>
        <v-card-title>Delete Department</v-card-title>
        <v-card-text>
          <p>
            Delete department
            <strong>{{ deleteTarget?.name }}</strong>? This removes all member
            associations, AI config, source subscriptions, and assessments
            scoped to this department. <strong>This cannot be undone.</strong>
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="deleteDialog = false">Cancel</v-btn>
          <v-btn color="error" :loading="deleting" @click="doDelete">Delete</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
