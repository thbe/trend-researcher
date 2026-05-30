import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// Vitest config kept separate from vite.config.ts on purpose:
// the dev/build pipeline does not need vuetify auto-imports during unit
// tests, and Vuetify's vite plugin pulls in a full SSR-style component
// scan that slows the test runner. Components-under-test stub out
// Vuetify globals via `global.stubs` in mount options instead.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.spec.ts'],
    // jsdom + Node 22 doesn't ship a usable localStorage. test-setup.ts
    // installs a minimal in-memory Storage shim so session/store tests run.
    setupFiles: ['./test-setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/stores/**', 'src/lib/**', 'src/components/**'],
    },
  },
})
