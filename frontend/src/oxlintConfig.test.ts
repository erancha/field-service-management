import { describe, expect, it } from 'vitest'
import oxlintrc from '../.oxlintrc.json'

// Guards that the exhaustive-deps rule the codebase relies on stays enabled. Several useEffect
// call sites carry `eslint-disable-next-line react-hooks/exhaustive-deps` directives; those
// directives suppress nothing — and silently rot into false assurances — unless oxlint actually
// runs the rule. oxlint keys it as `react/exhaustive-deps` (ESLint's `react-hooks/` prefix is the
// diagnostic label, not the config key).
const config: { rules?: Record<string, unknown> } = oxlintrc

describe('.oxlintrc.json', () => {
  it('enables react/exhaustive-deps', () => {
    const level = config.rules?.['react/exhaustive-deps']
    const severity = Array.isArray(level) ? level[0] : level
    expect(severity).toBeDefined()
    expect(severity).not.toBe('off')
  })
})
