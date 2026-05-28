<script setup lang="ts">
// App shell — same-origin SPA served by FastAPI in prod (CONTEXT G2),
// fronted by Vite dev server with /api proxy in dev (CONTEXT G8).
import { computed, ref } from 'vue'
import AppBar from '@/components/AppBar.vue'
import NavDrawer from '@/components/NavDrawer.vue'
import { useUiStore } from '@/stores/ui'

const drawerOpen = ref(true)
const ui = useUiStore()

// Two-way bind v-snackbar to the store: closing the snackbar (timeout or
// user dismiss) clears the message so a repeated identical notification
// still re-fires.
const snackbarOpen = computed({
  get: () => ui.snackbar !== null,
  set: (v: boolean) => {
    if (!v) ui.clear()
  },
})
</script>

<template>
  <v-app>
    <AppBar v-model="drawerOpen" />
    <NavDrawer v-model="drawerOpen" />
    <v-main>
      <v-container fluid class="pa-6">
        <router-view />
      </v-container>
    </v-main>
    <v-snackbar
      v-model="snackbarOpen"
      :color="ui.snackbar?.color ?? 'info'"
      :timeout="ui.snackbar?.timeout ?? 4000"
      location="bottom right"
    >
      {{ ui.snackbar?.text }}
      <template #actions>
        <v-btn variant="text" @click="ui.clear()">Close</v-btn>
      </template>
    </v-snackbar>
  </v-app>
</template>
