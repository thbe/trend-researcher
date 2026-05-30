import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // CONTEXT.md G8: SPA always fetches relative /api/* paths.
      // In dev, Vite proxies them to the FastAPI service on host :8088.
      // Host :8000 is reserved for oMLX on macOS — see README "Port allocation".
      // In prod (Plan 04-05), FastAPI serves dist/ same-origin so
      // the same fetch paths resolve without a proxy.
      '/api': {
        target: 'http://localhost:8088',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
