/** Renders a moment in the viewer's timezone and locale, to the minute, for people-facing text. */
export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}
