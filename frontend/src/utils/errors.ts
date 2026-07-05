/**
 * Extracts a user-facing message from a caught value.
 *
 * Catch clauses receive `unknown`; anything other than an Error carries no displayable
 * message, so the caller-supplied fallback is used instead.
 */
export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}
