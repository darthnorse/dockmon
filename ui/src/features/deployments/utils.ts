/**
 * Deployment Feature Utilities
 */

import { toast } from 'sonner'

/**
 * Extract error message from unknown error and show toast notification.
 * Consolidates the repeated error handling pattern across the feature.
 */
export function handleApiError(error: unknown, operation: string): void {
  const errorMessage = error instanceof Error ? error.message : String(error)
  toast.error(`Failed to ${operation}: ${errorMessage}`)
}

/**
 * Extract error message from unknown error.
 */
export function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/**
 * Deep-equal for a stack's env-file map (order-independent).
 * Used for unsaved-change detection in the editor.
 */
export function envFilesEqual(
  a: Record<string, string>,
  b: Record<string, string>
): boolean {
  const aKeys = Object.keys(a)
  const bKeys = Object.keys(b)
  if (aKeys.length !== bKeys.length) return false
  return aKeys.every((k) => Object.prototype.hasOwnProperty.call(b, k) && a[k] === b[k])
}

/**
 * Strip a leading "./" so an env filename is the bare basename the stack stores.
 * Mirrors the backend `normalize_env_filename`.
 */
export function normalizeEnvFileName(name: string): string {
  return name.startsWith('./') ? name.slice(2) : name
}

/**
 * Validate an env-file name for the stack editor's "add env file" control.
 * Stricter than the backend `is_safe_env_filename`: it rejects the same unsafe
 * forms (empty, ".", "..", path separators, absolute paths, leading/trailing
 * whitespace) and additionally rejects internal spaces, which the backend
 * tolerates but are undesirable in a filename. The backend remains the
 * authoritative gate. Returns a user-facing error message, or null when valid.
 */
export function validateEnvFileName(name: string): string | null {
  if (!name) return 'Filename is required'
  const candidate = normalizeEnvFileName(name)
  if (!candidate || candidate === '.' || candidate === '..') {
    return 'Enter a valid filename (e.g. .env, .db.env)'
  }
  if (candidate !== candidate.trim()) {
    return 'Filename cannot have leading or trailing spaces'
  }
  if (candidate.includes('/') || candidate.includes('\\') || candidate.includes(' ')) {
    return 'Filename cannot contain spaces or path separators'
  }
  return null
}
