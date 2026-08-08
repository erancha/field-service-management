import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The proxy is what assigns the two identical backends their roles: the SSE stream always lands on
// backend-1 and the publish POST on backend-2, so a posted event must cross processes via Redis.
export default defineConfig({
  plugins: [react()],
  // Off the source tree because the page's sources are mounted read-only in the container.
  cacheDir: '/tmp/vite-sse-sample',
  server: {
    host: true,
    port: 8010,
    strictPort: true,
    // The shared SSE hook lives outside this Vite root, up at the repo's frontend/src.
    fs: { allow: [fileURLToPath(new URL('../../..', import.meta.url))] },
    proxy: {
      '/api/events': { target: 'http://backend-1:8000', changeOrigin: true },
      '/api/publish': { target: 'http://backend-2:8000', changeOrigin: true },
    },
  },
})
