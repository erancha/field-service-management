import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// @testing-library/react's own auto-cleanup only registers when a global `afterEach`
// exists, which requires vitest's `test.globals` option; this project keeps globals
// off, so cleanup is wired explicitly to keep each test's DOM isolated.
afterEach(() => {
  cleanup()
})
