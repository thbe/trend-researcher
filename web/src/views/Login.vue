<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useSessionStore, type LoginPayload } from '@/stores/session'

const router = useRouter()
const route = useRoute()
const session = useSessionStore()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

async function handleLogin() {
  loading.value = true
  error.value = null
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.value, password: password.value }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      error.value = body.detail || `Login failed (${res.status})`
      return
    }
    const body = (await res.json().catch(() => ({}))) as LoginPayload
    session.applyLoginResponse(body)
    // Honour ?redirect=… set by the router guard when an unauth user hit
    // a protected route. Only accept same-origin relative paths to avoid
    // open-redirect abuse via crafted query strings.
    const redirect = route.query.redirect
    if (typeof redirect === 'string' && redirect.startsWith('/') && !redirect.startsWith('//')) {
      router.push(redirect)
    } else {
      router.push({ name: 'dashboard' })
    }
  } catch (e: any) {
    error.value = e.message || 'Network error'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <v-container class="fill-height" fluid>
    <v-row align="center" justify="center">
      <v-col cols="12" sm="8" md="4">
        <v-card class="elevation-12">
          <v-toolbar color="primary" dark flat>
            <v-toolbar-title>Trend Researcher</v-toolbar-title>
          </v-toolbar>
          <v-card-text>
            <v-form @submit.prevent="handleLogin">
              <v-text-field
                v-model="username"
                label="Username"
                prepend-icon="mdi-account"
                autocomplete="username"
                :disabled="loading"
              />
              <v-text-field
                v-model="password"
                label="Password"
                prepend-icon="mdi-lock"
                type="password"
                autocomplete="current-password"
                :disabled="loading"
              />
              <v-alert v-if="error" type="error" density="compact" class="mb-4">
                {{ error }}
              </v-alert>
              <v-btn
                type="submit"
                color="primary"
                block
                :loading="loading"
                :disabled="!username || !password"
              >
                Sign In
              </v-btn>
            </v-form>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>
