<script setup lang="ts">
// App shell — same-origin SPA served by FastAPI in prod (CONTEXT G2),
// fronted by Vite dev server with /api proxy in dev (CONTEXT G8).
</script>

<template>
  <v-app>
    <v-app-bar color="secondary" density="comfortable" flat>
      <v-app-bar-title>
        <router-link
          to="/dashboard"
          class="d-inline-flex align-center text-inherit"
          style="text-decoration: none; color: inherit; cursor: pointer"
        >
          <v-icon icon="mdi-database-outline" class="mr-2" />
          Trend Researcher
        </router-link>
      </v-app-bar-title>
      <template #append>
        <v-btn to="/dashboard" variant="text">Dashboard</v-btn>
        <v-btn to="/topics" variant="text">Topics</v-btn>
        <v-btn to="/assessment" variant="text">Assessment</v-btn>
        <v-btn to="/config" variant="text">Sources</v-btn>
        <v-btn to="/ai-config" variant="text">AI</v-btn>
      </template>
    </v-app-bar>
    <v-main>
      <v-container fluid class="pa-6">
        <router-view />
      </v-container>
    </v-main>
  </v-app>
</template>
