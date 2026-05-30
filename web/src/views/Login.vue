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
      <v-col cols="12" sm="8" md="5" lg="4">
        <v-card class="elevation-8" rounded="lg">
          <v-card-item class="pa-6 pb-2">
            <div class="d-flex align-center">
              <v-icon icon="mdi-database-outline" color="primary" size="32" class="mr-3" />
              <div>
                <div class="text-h5 font-weight-medium">Trend Researcher</div>
                <div class="text-caption text-medium-emphasis">Sign in to continue</div>
              </div>
            </div>
          </v-card-item>
          <v-card-text class="pa-6 pt-4">
            <v-form @submit.prevent="handleLogin">
              <v-text-field
                v-model="username"
                label="Username"
                prepend-inner-icon="mdi-account"
                autocomplete="username"
                :disabled="loading"
                class="mb-2"
              />
              <v-text-field
                v-model="password"
                label="Password"
                prepend-inner-icon="mdi-lock"
                type="password"
                autocomplete="current-password"
                :disabled="loading"
                class="mb-2"
              />
              <v-alert v-if="error" type="error" density="compact" variant="tonal" class="mb-4">
                {{ error }}
              </v-alert>
              <v-btn
                type="submit"
                color="primary"
                variant="flat"
                size="large"
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
