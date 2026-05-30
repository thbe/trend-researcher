<script setup lang="ts">
// Admin — unified superadmin view for Users + Departments management.
//
// Combines user CRUD, department CRUD, and department membership assignment
// into a single page with tabs. The "Add Member" form uses a user-picker
// (autocomplete from /api/users) instead of requiring raw UUIDs.

import { computed, onMounted, ref } from 'vue'

import {
  createUser,
  deleteUser,
  listUsers,
  resetUserPassword,
  type UserCreateRequest,
  type UserResponse,
} from '@/api/users'

import {
  addMember,
  createDepartment,
  deleteDepartment,
  listDepartments,
  listMembers,
  removeMember,
  updateDepartment,
  updateMember,
  type Department,
  type DepartmentRole,
  type Member,
} from '@/api/departments'

import { useSessionStore } from '@/stores/session'

const session = useSessionStore()

// ---------------------------------------------------------------------------
// Tab state
// ---------------------------------------------------------------------------
const activeTab = ref('users')

// ---------------------------------------------------------------------------
// Users tab
// ---------------------------------------------------------------------------
const users = ref<UserResponse[]>([])
const usersLoading = ref(false)
const usersError = ref<string | null>(null)
const usersSuccess = ref<string | null>(null)

const createUserDialog = ref(false)
const creatingUser = ref(false)
const userForm = ref({ username: '', password: '', password_confirm: '', is_superadmin: false })

const deleteUserDialog = ref(false)
const deletingUser = ref(false)
const deleteUserTarget = ref<UserResponse | null>(null)

// Password reset state
const resetUserDialog = ref(false)
const resettingUser = ref(false)
const resetUserTarget = ref<UserResponse | null>(null)
const resetUserForm = ref({ password: '', password_confirm: '' })

const userHeaders = [
  { title: 'Username', key: 'username' },
  { title: 'Role', key: 'role', sortable: false },
  { title: 'Created', key: 'created_at' },
  { title: 'Actions', key: 'actions', sortable: false, align: 'end' as const },
]

async function loadUsers() {
  usersLoading.value = true
  usersError.value = null
  try {
    const body = await listUsers()
    users.value = body.users
  } catch (e: any) {
    usersError.value = e.message || 'Failed to load users'
  } finally {
    usersLoading.value = false
  }
}

function openCreateUser() {
  userForm.value = { username: '', password: '', password_confirm: '', is_superadmin: false }
  createUserDialog.value = true
}

async function doCreateUser() {
  if (userForm.value.password !== userForm.value.password_confirm) {
    usersError.value = 'Passwords do not match'
    return
  }
  creatingUser.value = true
  usersError.value = null
  try {
    const { password_confirm: _pc, ...payload } = userForm.value
    await createUser(payload as UserCreateRequest)
    usersSuccess.value = `User "${userForm.value.username}" created`
    createUserDialog.value = false
    await loadUsers()
  } catch (e: any) {
    usersError.value = e.message || 'Failed to create user'
  } finally {
    creatingUser.value = false
  }
}

function openDeleteUser(user: UserResponse) {
  deleteUserTarget.value = user
  deleteUserDialog.value = true
}

async function doDeleteUser() {
  if (!deleteUserTarget.value) return
  deletingUser.value = true
  usersError.value = null
  try {
    await deleteUser(deleteUserTarget.value.id)
    usersSuccess.value = `User "${deleteUserTarget.value.username}" deactivated`
    deleteUserDialog.value = false
    await loadUsers()
  } catch (e: any) {
    usersError.value = e.message || 'Failed to deactivate user'
  } finally {
    deletingUser.value = false
  }
}

function openResetUser(user: UserResponse) {
  resetUserTarget.value = user
  resetUserForm.value = { password: '', password_confirm: '' }
  resetUserDialog.value = true
}

async function doResetUser() {
  if (!resetUserTarget.value) return
  if (resetUserForm.value.password !== resetUserForm.value.password_confirm) {
    usersError.value = 'Passwords do not match'
    return
  }
  resettingUser.value = true
  usersError.value = null
  try {
    await resetUserPassword(resetUserTarget.value.id, resetUserForm.value.password)
    usersSuccess.value = `Password reset for "${resetUserTarget.value.username}"`
    resetUserDialog.value = false
  } catch (e: any) {
    usersError.value = e.message || 'Failed to reset password'
  } finally {
    resettingUser.value = false
  }
}

// ---------------------------------------------------------------------------
// Departments tab
// ---------------------------------------------------------------------------
const departments = ref<Department[]>([])
const deptsLoading = ref(false)
const deptsError = ref<string | null>(null)
const deptsSuccess = ref<string | null>(null)

const createDeptDialog = ref(false)
const creatingDept = ref(false)
const deptForm = ref({ name: '', slug: '', description: '' })

const renameDeptDialog = ref(false)
const renamingDept = ref(false)
const renameTarget = ref<Department | null>(null)
const renameForm = ref({ name: '', description: '' })

const deleteDeptDialog = ref(false)
const deletingDept = ref(false)
const deleteDeptTarget = ref<Department | null>(null)

// Selected department for members panel
const selectedDept = ref<Department | null>(null)
const members = ref<Member[]>([])
const membersLoading = ref(false)

// Add member form — user picker
const addMemberForm = ref<{ user: UserResponse | null; role: DepartmentRole }>({
  user: null,
  role: 'viewer',
})
const addingMember = ref(false)

// Role change tracking
const updatingRole = ref<Record<string, boolean>>({})

// Remove member
const removeMemberDialog = ref(false)
const removingMember = ref(false)
const removeMemberTarget = ref<Member | null>(null)

const memberHeaders = [
  { title: 'Username', key: 'username' },
  { title: 'Role', key: 'role', sortable: false },
  { title: 'Added', key: 'created_at' },
  { title: 'Actions', key: 'actions', sortable: false, align: 'end' as const },
]

const roleItems: { title: string; value: DepartmentRole }[] = [
  { title: 'Viewer', value: 'viewer' },
  { title: 'Analyst', value: 'analyst' },
  { title: 'Dept Lead', value: 'dept_lead' },
]

// Users not already in the selected department (for the picker)
const availableUsers = computed(() => {
  const memberIds = new Set(members.value.map((m) => m.user_id))
  return users.value.filter((u) => !memberIds.has(u.id))
})

async function loadDepartments() {
  deptsLoading.value = true
  deptsError.value = null
  try {
    const body = await listDepartments()
    departments.value = body.departments
  } catch (e: any) {
    deptsError.value = e.message || 'Failed to load departments'
  } finally {
    deptsLoading.value = false
  }
}

async function selectDept(dept: Department) {
  selectedDept.value = dept
  membersLoading.value = true
  deptsError.value = null
  try {
    const m = await listMembers(dept.id)
    members.value = m.members
  } catch (e: any) {
    deptsError.value = e.message || 'Failed to load members'
  } finally {
    membersLoading.value = false
  }
}

function openCreateDept() {
  deptForm.value = { name: '', slug: '', description: '' }
  createDeptDialog.value = true
}

async function doCreateDept() {
  creatingDept.value = true
  deptsError.value = null
  try {
    await createDepartment({
      name: deptForm.value.name.trim(),
      slug: deptForm.value.slug.trim(),
      description: deptForm.value.description.trim() || null,
    })
    deptsSuccess.value = `Department "${deptForm.value.name}" created`
    createDeptDialog.value = false
    await loadDepartments()
    // Superadmin sees ALL departments in the session payload — refresh
    // so the new dept appears in the AppBar switcher + becomes available
    // as a valid X-Active-Department value without a re-login.
    await session.refresh()
  } catch (e: any) {
    deptsError.value = e.message || 'Failed to create department'
  } finally {
    creatingDept.value = false
  }
}

function openRenameDept(dept: Department) {
  renameTarget.value = dept
  renameForm.value = { name: dept.name, description: dept.description ?? '' }
  renameDeptDialog.value = true
}

async function doRenameDept() {
  if (!renameTarget.value) return
  renamingDept.value = true
  deptsError.value = null
  try {
    await updateDepartment(renameTarget.value.id, {
      name: renameForm.value.name.trim(),
      description: renameForm.value.description.trim() || null,
    })
    deptsSuccess.value = 'Department updated'
    renameDeptDialog.value = false
    await loadDepartments()
  } catch (e: any) {
    deptsError.value = e.message || 'Failed to update department'
  } finally {
    renamingDept.value = false
  }
}

function openDeleteDept(dept: Department) {
  deleteDeptTarget.value = dept
  deleteDeptDialog.value = true
}

async function doDeleteDept() {
  if (!deleteDeptTarget.value) return
  deletingDept.value = true
  deptsError.value = null
  try {
    await deleteDepartment(deleteDeptTarget.value.id)
    deptsSuccess.value = `Department "${deleteDeptTarget.value.name}" deleted`
    deleteDeptDialog.value = false
    if (selectedDept.value?.id === deleteDeptTarget.value.id) {
      selectedDept.value = null
      members.value = []
    }
    await loadDepartments()
    // Drop the deleted dept from the superadmin session payload + reselect
    // an active dept if the deleted one was active.
    await session.refresh()
  } catch (e: any) {
    deptsError.value = e.message || 'Failed to delete department'
  } finally {
    deletingDept.value = false
  }
}

async function doAddMember() {
  if (!addMemberForm.value.user || !selectedDept.value) return
  addingMember.value = true
  deptsError.value = null
  try {
    await addMember(selectedDept.value.id, {
      user_id: addMemberForm.value.user.id,
      role: addMemberForm.value.role,
    })
    deptsSuccess.value = `Added ${addMemberForm.value.user.username}`
    // If the admin just added themselves to this department, the session
    // payload needs to gain the new role membership so subsequent calls
    // resolve canEditDeptConfig / canAssess correctly.
    if (addMemberForm.value.user.username === session.user?.username) {
      await session.refresh()
    }
    addMemberForm.value = { user: null, role: 'viewer' }
    await selectDept(selectedDept.value)
  } catch (e: any) {
    deptsError.value = e.message || 'Failed to add member'
  } finally {
    addingMember.value = false
  }
}

async function changeRole(member: Member, newRole: DepartmentRole) {
  if (!selectedDept.value || newRole === member.role) return
  const prev = member.role
  member.role = newRole
  updatingRole.value[member.user_id] = true
  deptsError.value = null
  try {
    const updated = await updateMember(selectedDept.value.id, member.user_id, { role: newRole })
    Object.assign(member, updated)
    deptsSuccess.value = `Role updated for ${member.username}`
  } catch (e: any) {
    member.role = prev
    deptsError.value = e.message || 'Failed to update role'
  } finally {
    updatingRole.value[member.user_id] = false
  }
}

function openRemoveMember(member: Member) {
  removeMemberTarget.value = member
  removeMemberDialog.value = true
}

async function doRemoveMember() {
  if (!removeMemberTarget.value || !selectedDept.value) return
  removingMember.value = true
  deptsError.value = null
  try {
    await removeMember(selectedDept.value.id, removeMemberTarget.value.user_id)
    deptsSuccess.value = `Removed ${removeMemberTarget.value.username}`
    removeMemberDialog.value = false
    await selectDept(selectedDept.value)
  } catch (e: any) {
    deptsError.value = e.message || 'Failed to remove member'
  } finally {
    removingMember.value = false
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(async () => {
  await Promise.all([loadUsers(), loadDepartments()])
})
</script>

<template>
  <v-container>
    <h1 class="text-h4 mb-4">Administration</h1>

    <v-tabs v-model="activeTab" class="mb-4">
      <v-tab value="users">Users</v-tab>
      <v-tab value="departments">Departments &amp; Members</v-tab>
    </v-tabs>

    <!-- ================================================================= -->
    <!-- USERS TAB                                                          -->
    <!-- ================================================================= -->
    <div v-show="activeTab === 'users'">
      <v-alert v-if="usersError" type="error" closable class="mb-4" @click:close="usersError = null">
        {{ usersError }}
      </v-alert>
      <v-alert v-if="usersSuccess" type="success" closable class="mb-4" @click:close="usersSuccess = null">
        {{ usersSuccess }}
      </v-alert>

      <div class="d-flex align-center mb-3">
        <span class="text-subtitle-1 font-weight-medium">All Users</span>
        <v-spacer />
        <v-btn color="primary" prepend-icon="mdi-plus" size="small" @click="openCreateUser">
          New User
        </v-btn>
      </div>

      <v-card>
        <v-data-table
          :headers="userHeaders"
          :items="users"
          :loading="usersLoading"
          item-value="id"
        >
          <template #item.role="{ item }">
            <v-chip v-if="item.is_superadmin" color="primary" size="small" label>Superadmin</v-chip>
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
              @click.stop="openResetUser(item)"
            />
            <v-btn
              icon="mdi-account-off"
              size="small"
              variant="text"
              color="error"
              title="Deactivate"
              @click.stop="openDeleteUser(item)"
            />
          </template>
        </v-data-table>
      </v-card>
    </div>

    <!-- ================================================================= -->
    <!-- DEPARTMENTS TAB                                                    -->
    <!-- ================================================================= -->
    <div v-show="activeTab === 'departments'">
      <v-alert v-if="deptsError" type="error" closable class="mb-4" @click:close="deptsError = null">
        {{ deptsError }}
      </v-alert>
      <v-alert v-if="deptsSuccess" type="success" closable class="mb-4" @click:close="deptsSuccess = null">
        {{ deptsSuccess }}
      </v-alert>

      <v-row>
        <!-- Left: department list -->
        <v-col cols="12" md="5">
          <div class="d-flex align-center mb-3">
            <span class="text-subtitle-1 font-weight-medium">Departments</span>
            <v-spacer />
            <v-btn color="primary" prepend-icon="mdi-plus" size="small" @click="openCreateDept">
              New
            </v-btn>
          </div>

          <v-card>
            <v-list density="comfortable" nav>
              <v-list-item
                v-for="dept in departments"
                :key="dept.id"
                :active="selectedDept?.id === dept.id"
                @click="selectDept(dept)"
              >
                <v-list-item-title>{{ dept.name }}</v-list-item-title>
                <v-list-item-subtitle>{{ dept.slug }}</v-list-item-subtitle>
                <template #append>
                  <v-btn
                    icon="mdi-pencil"
                    size="x-small"
                    variant="text"
                    @click.stop="openRenameDept(dept)"
                  />
                  <v-btn
                    v-if="dept.slug !== 'default'"
                    icon="mdi-delete"
                    size="x-small"
                    variant="text"
                    color="error"
                    @click.stop="openDeleteDept(dept)"
                  />
                </template>
              </v-list-item>
            </v-list>
          </v-card>
        </v-col>

        <!-- Right: members of selected department -->
        <v-col cols="12" md="7">
          <template v-if="selectedDept">
            <div class="text-subtitle-1 font-weight-medium mb-3">
              Members of {{ selectedDept.name }}
            </div>

            <!-- Add member with user picker -->
            <v-card class="mb-3 pa-3">
              <v-row dense align="center">
                <v-col cols="12" sm="6">
                  <v-autocomplete
                    v-model="addMemberForm.user"
                    :items="availableUsers"
                    item-title="username"
                    item-value="id"
                    return-object
                    label="Select user"
                    density="compact"
                    hide-details
                    clearable
                  />
                </v-col>
                <v-col cols="6" sm="3">
                  <v-select
                    v-model="addMemberForm.role"
                    :items="roleItems"
                    label="Role"
                    density="compact"
                    hide-details
                  />
                </v-col>
                <v-col cols="6" sm="3">
                  <v-btn
                    color="primary"
                    :loading="addingMember"
                    :disabled="!addMemberForm.user"
                    block
                    size="small"
                    @click="doAddMember"
                  >
                    Add
                  </v-btn>
                </v-col>
              </v-row>
            </v-card>

            <v-card>
              <v-data-table
                :headers="memberHeaders"
                :items="members"
                :loading="membersLoading"
                item-value="user_id"
                density="comfortable"
              >
                <template #item.role="{ item }">
                  <v-select
                    :model-value="item.role"
                    :items="roleItems"
                    :loading="updatingRole[item.user_id]"
                    :disabled="updatingRole[item.user_id]"
                    density="compact"
                    hide-details
                    variant="outlined"
                    style="max-width: 150px"
                    @update:model-value="(v: DepartmentRole) => changeRole(item, v)"
                  />
                </template>
                <template #item.created_at="{ item }">
                  {{ new Date(item.created_at).toLocaleDateString() }}
                </template>
                <template #item.actions="{ item }">
                  <v-btn
                    icon="mdi-close"
                    size="small"
                    variant="text"
                    color="error"
                    title="Remove from department"
                    @click="openRemoveMember(item)"
                  />
                </template>
              </v-data-table>
            </v-card>
          </template>

          <v-card v-else class="pa-6 text-center text-medium-emphasis">
            <v-icon size="48" class="mb-2">mdi-arrow-left</v-icon>
            <div>Select a department to manage its members</div>
          </v-card>
        </v-col>
      </v-row>
    </div>

    <!-- ================================================================= -->
    <!-- DIALOGS                                                            -->
    <!-- ================================================================= -->

    <!-- Create user -->
    <v-dialog v-model="createUserDialog" max-width="500">
      <v-card>
        <v-card-title>New User</v-card-title>
        <v-card-text>
          <v-text-field v-model="userForm.username" label="Username" hint="Case-insensitive" persistent-hint class="mb-2" />
          <v-text-field v-model="userForm.password" label="Password" type="password" hint="Min 6 characters" persistent-hint class="mb-2" />
          <v-text-field
            v-model="userForm.password_confirm"
            label="Confirm password"
            type="password"
            :error="userForm.password_confirm.length > 0 && userForm.password_confirm !== userForm.password"
            :error-messages="userForm.password_confirm.length > 0 && userForm.password_confirm !== userForm.password ? ['Passwords do not match'] : []"
            class="mb-2"
          />
          <v-checkbox v-model="userForm.is_superadmin" label="Superadmin" hint="Full platform access" persistent-hint />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="createUserDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            :loading="creatingUser"
            :disabled="!userForm.username.trim() || userForm.password.length < 6 || userForm.password !== userForm.password_confirm"
            @click="doCreateUser"
          >Create</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Reset user password -->
    <v-dialog v-model="resetUserDialog" max-width="500">
      <v-card>
        <v-card-title>Reset Password</v-card-title>
        <v-card-text>
          <p class="mb-3">
            Set a new password for <strong>{{ resetUserTarget?.username }}</strong>.
            They will need to use the new password on next sign-in.
          </p>
          <v-text-field
            v-model="resetUserForm.password"
            label="New password"
            type="password"
            hint="Min 6 characters"
            persistent-hint
            class="mb-2"
          />
          <v-text-field
            v-model="resetUserForm.password_confirm"
            label="Confirm new password"
            type="password"
            :error="resetUserForm.password_confirm.length > 0 && resetUserForm.password_confirm !== resetUserForm.password"
            :error-messages="resetUserForm.password_confirm.length > 0 && resetUserForm.password_confirm !== resetUserForm.password ? ['Passwords do not match'] : []"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="resetUserDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            :loading="resettingUser"
            :disabled="resetUserForm.password.length < 6 || resetUserForm.password !== resetUserForm.password_confirm"
            @click="doResetUser"
          >Reset password</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Deactivate user -->
    <v-dialog v-model="deleteUserDialog" max-width="450">
      <v-card>
        <v-card-title>Deactivate User</v-card-title>
        <v-card-text>
          Deactivate <strong>{{ deleteUserTarget?.username }}</strong>? They will no longer be able to sign in.
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="deleteUserDialog = false">Cancel</v-btn>
          <v-btn color="error" :loading="deletingUser" @click="doDeleteUser">Deactivate</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Create department -->
    <v-dialog v-model="createDeptDialog" max-width="500">
      <v-card>
        <v-card-title>New Department</v-card-title>
        <v-card-text>
          <v-text-field v-model="deptForm.name" label="Name" class="mb-2" />
          <v-text-field v-model="deptForm.slug" label="Slug" hint="Lowercase identifier" persistent-hint class="mb-2" />
          <v-textarea v-model="deptForm.description" label="Description (optional)" rows="2" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="createDeptDialog = false">Cancel</v-btn>
          <v-btn color="primary" :loading="creatingDept" :disabled="!deptForm.name.trim() || !deptForm.slug.trim()" @click="doCreateDept">Create</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Rename department -->
    <v-dialog v-model="renameDeptDialog" max-width="500">
      <v-card>
        <v-card-title>Edit Department</v-card-title>
        <v-card-text>
          <v-text-field v-model="renameForm.name" label="Name" class="mb-2" />
          <v-textarea v-model="renameForm.description" label="Description" rows="2" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="renameDeptDialog = false">Cancel</v-btn>
          <v-btn color="primary" :loading="renamingDept" :disabled="!renameForm.name.trim()" @click="doRenameDept">Save</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete department -->
    <v-dialog v-model="deleteDeptDialog" max-width="450">
      <v-card>
        <v-card-title>Delete Department</v-card-title>
        <v-card-text>
          Delete <strong>{{ deleteDeptTarget?.name }}</strong>? All members, config, and assessments scoped to this department will be removed. <strong>This cannot be undone.</strong>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="deleteDeptDialog = false">Cancel</v-btn>
          <v-btn color="error" :loading="deletingDept" @click="doDeleteDept">Delete</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Remove member -->
    <v-dialog v-model="removeMemberDialog" max-width="450">
      <v-card>
        <v-card-title>Remove Member</v-card-title>
        <v-card-text>
          Remove <strong>{{ removeMemberTarget?.username }}</strong> from <strong>{{ selectedDept?.name }}</strong>?
          <p class="text-caption text-medium-emphasis mt-2">The user keeps their account; they just lose access to this department.</p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="removeMemberDialog = false">Cancel</v-btn>
          <v-btn color="error" :loading="removingMember" @click="doRemoveMember">Remove</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
