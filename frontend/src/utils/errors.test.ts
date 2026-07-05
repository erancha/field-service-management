import { describe, expect, it } from 'vitest'
import { errorMessage } from './errors.ts'

describe('errorMessage', () => {
  it('returns the message of an Error', () => {
    expect(errorMessage(new Error('boom'), 'fallback')).toBe('boom')
  })

  it('returns the fallback for a thrown non-Error value', () => {
    expect(errorMessage('raw string failure', 'fallback')).toBe('fallback')
  })
})
