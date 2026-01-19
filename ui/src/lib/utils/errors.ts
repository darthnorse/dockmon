/**
 * Error handling utilities
 */

import { ApiError } from '@/lib/api/client'

/**
 * Extract error message from an API error response
 *
 * Handles both ApiError instances and generic errors, extracting
 * the most specific error message available.
 *
 * @example
 * getErrorMessage(error, 'Failed to load data') // Returns detail from API or fallback
 */
export function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    // ApiError stores structured data
    if (typeof error.data === 'object' && error.data !== null && 'detail' in error.data) {
      const detail = (error.data as { detail?: string }).detail
      if (detail) return detail
    }
    if (error.message) return error.message
  }

  // Handle generic errors
  if (error instanceof Error && error.message) {
    return error.message
  }

  return fallback
}
