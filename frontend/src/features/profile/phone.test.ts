import { describe, expect, it } from 'vitest'
import { isValidPhone, isIsraeliPhone } from './phone.ts'

describe('isValidPhone (E.164 gate: block only clearly-malformed input)', () => {
  it('accepts any 7–15 digit number, local or international', () => {
    expect(isValidPhone('054-1234567')).toBe(true)
    expect(isValidPhone('+972-54-1234567')).toBe(true)
    expect(isValidPhone('+1-202-555-0143')).toBe(true) // US
    expect(isValidPhone('055-12345678')).toBe(true) // 11 digits — allowed, though not a valid IL mobile
    expect(isValidPhone('(054) 123-4567')).toBe(true)
  })

  it('rejects too-short, too-long, or non-numeric input', () => {
    expect(isValidPhone('12345')).toBe(false) // 5 digits
    expect(isValidPhone('0123456789012345')).toBe(false) // 16 digits
    expect(isValidPhone('')).toBe(false)
    expect(isValidPhone('   ')).toBe(false)
    expect(isValidPhone('call me')).toBe(false)
    expect(isValidPhone('054/1234567')).toBe(false)
  })
})

describe('isIsraeliPhone (drives the soft warning)', () => {
  it('recognizes Israeli mobiles and landlines, local and +972', () => {
    expect(isIsraeliPhone('054-1234567')).toBe(true)
    expect(isIsraeliPhone('+972-54-1234567')).toBe(true)
    expect(isIsraeliPhone('03-1234567')).toBe(true)
  })

  it('does not recognize foreign or malformed-Israeli numbers', () => {
    expect(isIsraeliPhone('+1-202-555-0143')).toBe(false)
    expect(isIsraeliPhone('055-12345678')).toBe(false) // 11 digits
    expect(isIsraeliPhone('054-123456')).toBe(false) // 9 digits
  })
})
