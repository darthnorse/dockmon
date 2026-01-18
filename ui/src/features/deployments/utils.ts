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
