<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getDashboard } from '@/api/dashboard'
import type { DashboardData } from '@/api/dashboard'

const router = useRouter()
const data = ref<DashboardData | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    data.value = await getDashboard()
  } finally {
    loading.value = false
  }
})

function goTopics() {
  router.push({ name: 'topics' })
}
function goOpportunities() {
  router.push({ name: 'assessment', query: { category: 'opportunity' } })
}
function goRisks() {
  router.push({ name: 'assessment', query: { category: 'risk' } })
}
function goAssessed() {
  router.push({ name: 'assessment' })
}
</script>

<template>
  <div>
    <h1 class="text-h4 mb-6">Dashboard</h1>

    <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-4" />

    <v-row v-if="data" class="mt-2">
      <v-col cols="12" sm="6" md="3">
        <v-card
          class="pa-4 text-center cursor-pointer"
          variant="outlined"
          @click="goTopics"
        >
          <v-icon icon="mdi-database-outline" size="48" color="primary" class="mb-2" />
          <div class="text-h3 font-weight-bold">{{ data.total_topics }}</div>
          <div class="text-subtitle-1 text-medium-emphasis">Total Topics</div>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6" md="3">
        <v-card
          class="pa-4 text-center cursor-pointer"
          variant="outlined"
          @click="goAssessed"
        >
          <v-icon icon="mdi-brain" size="48" color="secondary" class="mb-2" />
          <div class="text-h3 font-weight-bold">{{ data.assessed_topics }}</div>
          <div class="text-subtitle-1 text-medium-emphasis">Assessed</div>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6" md="3">
        <v-card
          class="pa-4 text-center cursor-pointer"
          variant="outlined"
          color="success"
          @click="goOpportunities"
        >
          <v-icon icon="mdi-trending-up" size="48" color="success" class="mb-2" />
          <div class="text-h3 font-weight-bold">{{ data.opportunities }}</div>
          <div class="text-subtitle-1 text-medium-emphasis">Opportunities</div>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6" md="3">
        <v-card
          class="pa-4 text-center cursor-pointer"
          variant="outlined"
          color="error"
          @click="goRisks"
        >
          <v-icon icon="mdi-alert-outline" size="48" color="error" class="mb-2" />
          <div class="text-h3 font-weight-bold">{{ data.risks }}</div>
          <div class="text-subtitle-1 text-medium-emphasis">Risks</div>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.cursor-pointer {
  cursor: pointer;
}
.cursor-pointer:hover {
  transform: translateY(-2px);
  transition: transform 0.2s;
}
</style>
