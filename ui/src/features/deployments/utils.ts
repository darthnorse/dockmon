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
