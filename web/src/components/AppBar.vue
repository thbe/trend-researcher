<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useSessionStore } from '@/stores/session'
import { STRINGS } from '@/lib/strings'
import DepartmentSwitcher from '@/components/DepartmentSwitcher.vue'

defineProps<{ modelValue?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const session = useSessionStore()
const router = useRouter()

async function onLogout() {
  await session.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <v-app-bar color="surface" density="comfortable" elevation="1" border>
    <v-app-bar-nav-icon
      v-if="session.isAuthenticated"
      @click="emit('update:modelValue', !modelValue)"
    />
    <v-app-bar-title>
      <router-link
        to="/dashboard"
        class="d-inline-flex align-center"
        style="text-decoration: none; color: inherit; cursor: pointer"
      >
        <v-icon icon="mdi-database-outline" color="primary" class="mr-2" />
        <span class="text-h6 font-weight-medium">{{ STRINGS.APP_NAME }}</span>
      </router-link>
    </v-app-bar-title>

    <template #append>
      <DepartmentSwitcher class="mr-3" />

      <v-menu v-if="session.isAuthenticated" location="bottom end">
        <template #activator="{ props: menuProps }">
          <v-btn icon v-bind="menuProps">
            <v-avatar color="primary" size="32">
              <span class="text-white text-caption">
                {{ session.user?.username?.charAt(0).toUpperCase() ?? '?' }}
              </span>
            </v-avatar>
          </v-btn>
        </template>
        <v-list density="compact" min-width="200">
          <v-list-item>
            <v-list-item-title>{{ session.user?.username }}</v-list-item-title>
            <v-list-item-subtitle v-if="session.isSuperadmin">
              {{ STRINGS.LABEL_SUPERADMIN }}
            </v-list-item-subtitle>
          </v-list-item>
          <v-divider />
          <v-list-item prepend-icon="mdi-logout" @click="onLogout">
            <v-list-item-title>{{ STRINGS.BTN_SIGN_OUT }}</v-list-item-title>
          </v-list-item>
        </v-list>
      </v-menu>
    </template>
  </v-app-bar>
</template>
