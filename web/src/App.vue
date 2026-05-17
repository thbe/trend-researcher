<script setup lang="ts">
// App shell — same-origin SPA served by FastAPI in prod (CONTEXT G2),
// fronted by Vite dev server with /api proxy in dev (CONTEXT G8).
</script>

<template>
  <v-app>
    <v-app-bar color="secondary" density="comfortable" flat>
      <v-app-bar-title>
        <v-icon icon="mdi-database-outline" class="mr-2" />
        Trend Researcher
      </v-app-bar-title>
    </v-app-bar>
    <v-main>
      <v-container fluid class="pa-6">
        <router-view />
      </v-container>
    </v-main>
  </v-app>
</template>
