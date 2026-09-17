/**
 * Deployment Feature Utilities
 */

import { toast } from 'sonner'
import { ApiError } from '@/lib/api/client'

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

/**
 * First line whose indentation uses a tab (1-based), or null. Block-scalar
 * (| / >) content is skipped — a tab there is literal, valid YAML.
 */
export function findIndentationTab(value: string): number | null {
  const lines = value.split('\n')
  let blockParentIndent: number | null = null
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? ''
    if (blockParentIndent !== null) {
      if (line.trim() === '') continue
      const spaces = /^ */.exec(line)?.[0].length ?? 0
      if (spaces > blockParentIndent) continue
      blockParentIndent = null
    }
    const leading = /^[ \t]*/.exec(line)?.[0] ?? ''
    if (leading.includes('\t')) return i + 1
    if (/(?::|^\s*-)\s+[|>][+\-0-9]*\s*(#.*)?$/.test(line)) {
      blockParentIndent = leading.length
    }
  }
  return null
}

/**
 * Message to surface for a malformed-compose (400) port-check failure, or null.
 * With unsaved edits, returns null so the save-first flow re-validates instead
 * of blocking a user who just fixed a bad saved stack in the editor.
 */
export function blockingComposeErrorMessage(
  err: unknown,
  hasUnsavedChanges: boolean,
): string | null {
  if (err instanceof ApiError && err.status === 400 && !hasUnsavedChanges) {
    return err.message
  }
  return null
}
