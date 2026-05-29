<script setup lang="ts">
// Users — superadmin list + create/deactivate.
//
// Backed by /api/users (list/create/delete). Superadmin-only view for
// managing platform users. Deactivation is soft-delete (is_active=false).

import { onMounted, ref } from 'vue'

import {
  createUser,
  deleteUser,
  listUsers,
  resetUserPassword,
  type UserResponse,
} from '@/api/users'

const users = ref<UserResponse[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)

// Create dialog state
const createDialog = ref(false)
const creating = ref(false)
const createForm = ref({ username: '', password: '', password_confirm: '', is_superadmin: false })

// Delete confirm dialog state
const deleteDialog = ref(false)
const deleting = ref(false)
const deleteTarget = ref<UserResponse | null>(null)

// Password reset dialog state
const resetDialog = ref(false)
const resetting = ref(false)
const resetTarget = ref<UserResponse | null>(null)
const resetForm = ref({ password: '', password_confirm: '' })

const headers = [
  { title: 'Username', key: 'username' },
  { title: 'Role', key: 'role', sortable: false },
  { title: 'Created', key: 'created_at' },
  { title: 'Actions', key: 'actions', sortable: false, align: 'end' as const },
]

async function load() {
  loading.value = true
  error.value = null
  try {
    const body = await listUsers()
    users.value = body.users
  } catch (e: any) {
    error.value = e.message || 'Failed to load users'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createForm.value = { username: '', password: '', password_confirm: '', is_superadmin: false }
  createDialog.value = true
}

async function doCreate() {
  if (createForm.value.password !== createForm.value.password_confirm) {
    error.value = 'Passwords do not match'
    return
  }
  creating.value = true
  error.value = null
  try {
    await createUser({
      username: createForm.value.username.trim(),
      password: createForm.value.password,
      is_superadmin: createForm.value.is_superadmin,
    })
    success.value = `User "${createForm.value.username}" created`
    createDialog.value = false
    await load()
  } catch (e: any) {
    error.value = e.message || 'Failed to create user'
  } finally {
    creating.value = false
  }
}

function openDelete(user: UserResponse) {
  deleteTarget.value = user
  deleteDialog.value = true
}

async function doDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  error.value = null
  try {
    await deleteUser(deleteTarget.value.id)
    success.value = `User "${deleteTarget.value.username}" deactivated`
    deleteDialog.value = false
    await load()
  } catch (e: any) {
    error.value = e.message || 'Failed to deactivate user'
  } finally {
    deleting.value = false
  }
}

function openReset(user: UserResponse) {
  resetTarget.value = user
  resetForm.value = { password: '', password_confirm: '' }
  resetDialog.value = true
}

async function doReset() {
  if (!resetTarget.value) return
  if (resetForm.value.password !== resetForm.value.password_confirm) {
    error.value = 'Passwords do not match'
    return
  }
  resetting.value = true
  error.value = null
  try {
    await resetUserPassword(resetTarget.value.id, resetForm.value.password)
    success.value = `Password reset for "${resetTarget.value.username}"`
    resetDialog.value = false
  } catch (e: any) {
    error.value = e.message || 'Failed to reset password'
  } finally {
    resetting.value = false
  }
}

onMounted(load)
</script>

<template>
  <v-container>
    <v-row>
      <v-col>
        <div class="d-flex align-center mb-4">
          <h1 class="text-h4">Users</h1>
          <v-spacer />
          <v-btn color="primary" prepend-icon="mdi-plus" @click="openCreate">
            New User
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
            :items="users"
            :loading="loading"
            item-value="id"
          >
            <template #item.role="{ item }">
              <v-chip
                v-if="item.is_superadmin"
                color="primary"
                size="small"
                label
              >
                Superadmin
              </v-chip>
              <v-chip v-else size="small" label>User</v-chip>
            </template>

            <template #item.created_at="{ item }">
              {{ new Date(item.created_at).toLocaleDateString() }}
            </template>

            <template #item.actions="{ item }">
              <v-btn
                icon="mdi-key-variant"
                size="small"
                variant="text"
                title="Reset password"
                @click.stop="openReset(item)"
              />
              <v-btn
                icon="mdi-account-off"
                size="small"
                variant="text"
                color="error"
                title="Deactivate user"
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
        <v-card-title>New User</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="createForm.username"
            label="Username"
            hint="Email or unique identifier (case-insensitive)"
            persistent-hint
            class="mb-2"
          />
          <v-text-field
            v-model="createForm.password"
            label="Password"
            type="password"
            hint="Minimum 6 characters"
            persistent-hint
            class="mb-2"
          />
          <v-text-field
            v-model="createForm.password_confirm"
            label="Confirm password"
            type="password"
            :error="createForm.password_confirm.length > 0 && createForm.password_confirm !== createForm.password"
            :error-messages="createForm.password_confirm.length > 0 && createForm.password_confirm !== createForm.password ? ['Passwords do not match'] : []"
            class="mb-2"
          />
          <v-checkbox
            v-model="createForm.is_superadmin"
            label="Superadmin"
            hint="Grants full platform access"
            persistent-hint
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="createDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            :loading="creating"
            :disabled="!createForm.username.trim() || createForm.password.length < 6 || createForm.password !== createForm.password_confirm"
            @click="doCreate"
          >
            Create
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Reset password dialog -->
    <v-dialog v-model="resetDialog" max-width="500">
      <v-card>
        <v-card-title>Reset Password</v-card-title>
        <v-card-text>
          <p class="mb-3">
            Set a new password for <strong>{{ resetTarget?.username }}</strong>.
            They will need to use the new password on next sign-in.
          </p>
          <v-text-field
            v-model="resetForm.password"
            label="New password"
            type="password"
            hint="Minimum 6 characters"
            persistent-hint
            class="mb-2"
          />
          <v-text-field
            v-model="resetForm.password_confirm"
            label="Confirm new password"
            type="password"
            :error="resetForm.password_confirm.length > 0 && resetForm.password_confirm !== resetForm.password"
            :error-messages="resetForm.password_confirm.length > 0 && resetForm.password_confirm !== resetForm.password ? ['Passwords do not match'] : []"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="resetDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            :loading="resetting"
            :disabled="resetForm.password.length < 6 || resetForm.password !== resetForm.password_confirm"
            @click="doReset"
          >
            Reset password
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete confirm dialog -->
    <v-dialog v-model="deleteDialog" max-width="450">
      <v-card>
        <v-card-title>Deactivate User</v-card-title>
        <v-card-text>
          <p>
            Deactivate user
            <strong>{{ deleteTarget?.username }}</strong>? They will no longer
            be able to sign in. This can be reversed by a database admin.
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="deleteDialog = false">Cancel</v-btn>
          <v-btn color="error" :loading="deleting" @click="doDelete">Deactivate</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
