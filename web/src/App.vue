<script setup lang="ts">
// App shell — same-origin SPA served by FastAPI in prod (CONTEXT G2),
// fronted by Vite dev server with /api proxy in dev (CONTEXT G8).
import { ref } from 'vue'
import AppBar from '@/components/AppBar.vue'
import NavDrawer from '@/components/NavDrawer.vue'

const drawerOpen = ref(true)
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
  </v-app>
</template>
