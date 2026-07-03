// Phone rules. The app serves an international audience, so entry is gated only on E.164 shape;
// numbers that pass the gate but are not valid Israeli numbers are allowed with a soft warning,
// since most users are expected to be Israeli. The same E.164 gate is enforced server-side.
const SEPARATORS_AND_DIGITS = /^\+?[\d\s()-]+$/
const IL_MOBILE_OR_NON_GEOGRAPHIC = /^0[57]\d{8}$/
const IL_GEOGRAPHIC_LANDLINE = /^0[23489]\d{7}$/

function digitsOf(value: string): string | null {
  const trimmed = value.trim()
  if (!SEPARATORS_AND_DIGITS.test(trimmed)) return null
  return trimmed.replace(/\D/g, '')
}

// E.164 allows at most 15 digits; 7 is a pragmatic lower bound that still admits every real number
// while rejecting obvious typos. This is the accept/reject boundary for phone entry.
export function isValidPhone(value: string): boolean {
  const digits = digitsOf(value)
  return digits !== null && digits.length >= 7 && digits.length <= 15
}

// True when the number matches the Israeli national numbering plan: mobile / non-geographic (05x,
// 07x) are 10 digits and geographic landlines (02, 03, 04, 08, 09) are 9, with +972 / 972
// normalized to the national 0-leading form.
export function isIsraeliPhone(value: string): boolean {
  let digits = digitsOf(value)
  if (digits === null) return false
  if (digits.startsWith('972')) digits = '0' + digits.slice(3)
  return IL_MOBILE_OR_NON_GEOGRAPHIC.test(digits) || IL_GEOGRAPHIC_LANDLINE.test(digits)
}
