<script setup lang="ts">
// DepartmentSettings — per-department members management (superadmin).
//
// Route: /departments/:id/settings
//
// Backend constraints handled here:
//   * No /api/users LIST endpoint exists. The add-member form takes a raw
//     UUID text input. (T05 discovery #5 — workaround until a user picker
//     endpoint lands.)
//   * POST /api/departments/{id}/members → 409 if user is already a member.
//   * PUT  /api/departments/{id}/members/{user_id} → 409 if demoting the
//     last dept_lead.
//   * DELETE /api/departments/{id}/members/{user_id} → 409 if removing the
//     last dept_lead.

import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  addMember,
  getDepartment,
  listMembers,
  removeMember,
  updateMember,
  type Department,
  type DepartmentRole,
  type Member,
} from '@/api/departments'

const route = useRoute()
const router = useRouter()

const deptId = computed(() => String(route.params.id ?? ''))

const dept = ref<Department | null>(null)
const members = ref<Member[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)

// Add-member form
const addForm = ref<{ user_id: string; role: DepartmentRole }>({
  user_id: '',
  role: 'viewer',
})
const adding = ref(false)

// Inline role-change saving flags by user_id
const updating = ref<Record<string, boolean>>({})

// Remove confirm dialog
const removeDialog = ref(false)
const removing = ref(false)
const removeTarget = ref<Member | null>(null)

const roleItems: { title: string; value: DepartmentRole }[] = [
  { title: 'Viewer', value: 'viewer' },
  { title: 'Analyst', value: 'analyst' },
  { title: 'Dept Lead', value: 'dept_lead' },
]

const headers = [
  { title: 'Username', key: 'username' },
  { title: 'User ID', key: 'user_id' },
  { title: 'Role', key: 'role', sortable: false },
  { title: 'Added', key: 'created_at' },
  { title: 'Actions', key: 'actions', sortable: false, align: 'end' as const },
]

async function load() {
  if (!deptId.value) return
  loading.value = true
  error.value = null
  try {
    const [d, m] = await Promise.all([getDepartment(deptId.value), listMembers(deptId.value)])
    dept.value = d
    members.value = m.members
  } catch (e: any) {
    error.value = e.message || 'Failed to load department'
  } finally {
    loading.value = false
  }
}

async function doAdd() {
  const uid = addForm.value.user_id.trim()
  if (!uid) return
  adding.value = true
  error.value = null
  try {
    await addMember(deptId.value, { user_id: uid, role: addForm.value.role })
    success.value = 'Member added'
    addForm.value = { user_id: '', role: 'viewer' }
    await load()
  } catch (e: any) {
    error.value = e.message || 'Failed to add member'
  } finally {
    adding.value = false
  }
}

async function changeRole(member: Member, newRole: DepartmentRole) {
  if (newRole === member.role) return
  const prev = member.role
  member.role = newRole
  updating.value[member.user_id] = true
  error.value = null
  try {
    const updated = await updateMember(deptId.value, member.user_id, { role: newRole })
    Object.assign(member, updated)
    success.value = `Role updated for ${member.username}`
  } catch (e: any) {
    member.role = prev
    // 409 → last dept_lead constraint
    error.value = e.message || 'Failed to update role'
  } finally {
    updating.value[member.user_id] = false
  }
}

function openRemove(member: Member) {
  removeTarget.value = member
  removeDialog.value = true
}

async function doRemove() {
  if (!removeTarget.value) return
  removing.value = true
  error.value = null
  try {
    await removeMember(deptId.value, removeTarget.value.user_id)
    success.value = `Removed ${removeTarget.value.username}`
    removeDialog.value = false
    await load()
  } catch (e: any) {
    // 409 → last dept_lead constraint
    error.value = e.message || 'Failed to remove member'
  } finally {
    removing.value = false
  }
}

onMounted(load)
</script>

<template>
  <v-container>
    <v-row>
      <v-col>
        <div class="d-flex align-center mb-1">
          <v-btn icon="mdi-arrow-left" variant="text" @click="router.push('/departments')" />
          <h1 class="text-h4 ml-2">{{ dept?.name ?? 'Department' }}</h1>
        </div>
        <div class="text-subtitle-2 text-medium-emphasis mb-4 ml-12">
          slug: <code>{{ dept?.slug ?? '—' }}</code> ·
          id: <code>{{ deptId }}</code>
        </div>

        <v-alert v-if="error" type="error" closable class="mb-4" @click:close="error = null">
          {{ error }}
        </v-alert>

        <v-alert v-if="success" type="success" closable class="mb-4" @click:close="success = null">
          {{ success }}
        </v-alert>

        <v-card class="mb-4">
          <v-card-title>Add Member</v-card-title>
          <v-card-subtitle>
            Paste a user UUID. (A user-picker endpoint isn't available yet — see API roadmap.)
          </v-card-subtitle>
          <v-card-text>
            <v-row dense>
              <v-col cols="12" md="7">
                <v-text-field
                  v-model="addForm.user_id"
                  label="User ID (UUID)"
                  placeholder="00000000-0000-0000-0000-000000000000"
                  hide-details
                  density="comfortable"
                />
              </v-col>
              <v-col cols="12" md="3">
                <v-select
                  v-model="addForm.role"
                  :items="roleItems"
                  label="Role"
                  hide-details
                  density="comfortable"
                />
              </v-col>
              <v-col cols="12" md="2" class="d-flex align-center">
                <v-btn
                  color="primary"
                  :loading="adding"
                  :disabled="!addForm.user_id.trim()"
                  block
                  @click="doAdd"
                >
                  Add
                </v-btn>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>

        <v-card>
          <v-card-title>Members</v-card-title>
          <v-data-table
            :headers="headers"
            :items="members"
            :loading="loading"
            item-value="user_id"
            density="comfortable"
          >
            <template #item.user_id="{ item }">
              <code class="text-caption">{{ item.user_id }}</code>
            </template>

            <template #item.role="{ item }">
              <v-select
                :model-value="item.role"
                :items="roleItems"
                :loading="updating[item.user_id]"
                :disabled="updating[item.user_id]"
                density="compact"
                hide-details
                variant="outlined"
                style="max-width: 160px"
                @update:model-value="(v: DepartmentRole) => changeRole(item, v)"
              />
            </template>

            <template #item.created_at="{ item }">
              {{ new Date(item.created_at).toLocaleDateString() }}
            </template>

            <template #item.actions="{ item }">
              <v-btn
                icon="mdi-delete"
                size="small"
                variant="text"
                color="error"
                title="Remove from department"
                @click="openRemove(item)"
              />
            </template>
          </v-data-table>
        </v-card>
      </v-col>
    </v-row>

    <!-- Remove confirm dialog -->
    <v-dialog v-model="removeDialog" max-width="450">
      <v-card>
        <v-card-title>Remove Member</v-card-title>
        <v-card-text>
          <p>
            Remove <strong>{{ removeTarget?.username }}</strong> from
            <strong>{{ dept?.name }}</strong>?
          </p>
          <p class="text-caption text-medium-emphasis mt-2">
            The user keeps their account; they just lose access to this department.
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="removeDialog = false">Cancel</v-btn>
          <v-btn color="error" :loading="removing" @click="doRemove">Remove</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
