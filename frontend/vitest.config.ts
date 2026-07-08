import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    // Threads start without forking a child process, so the jsdom worker comes up well within
    // vitest's fixed 60s startup window even on slow WSL filesystems where forks time out.
    pool: 'threads',
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
})
