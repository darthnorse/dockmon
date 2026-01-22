/**
 * Event utility functions
 */

import type { EventSeverity, EventCategory } from '@/types/events'

/**
 * Format severity for display (e.g., 'info' -> 'Info', 'critical' -> 'Critical')
 */
export function formatSeverity(severity: EventSeverity): string {
  return severity.charAt(0).toUpperCase() + severity.slice(1)
}

/**
 * Get severity badge color classes
 */
export function getSeverityColor(severity: EventSeverity): {
  bg: string
  text: string
  border: string
} {
  switch (severity) {
    case 'critical':
      return {
        bg: 'bg-red-500/20',
        text: 'text-red-500',
        border: 'border-red-500/30',
      }
    case 'error':
      return {
        bg: 'bg-orange-500/20',
        text: 'text-orange-500',
        border: 'border-orange-500/30',
      }
    case 'warning':
      return {
        bg: 'bg-yellow-500/20',
        text: 'text-yellow-500',
        border: 'border-yellow-500/30',
      }
    case 'info':
      return {
        bg: 'bg-blue-500/20',
        text: 'text-blue-500',
        border: 'border-blue-500/30',
      }
    case 'debug':
      return {
        bg: 'bg-gray-500/20',
        text: 'text-gray-500',
        border: 'border-gray-500/30',
      }
    default:
      return {
        bg: 'bg-muted',
        text: 'text-muted-foreground',
        border: 'border-border',
      }
  }
}

/**
 * Format category for display
 */
export function formatCategory(category: EventCategory): string {
  return category.charAt(0).toUpperCase() + category.slice(1)
}

/**
 * Get category icon color
 */
export function getCategoryColor(category: EventCategory): string {
  switch (category) {
    case 'container':
      return 'text-blue-500'
    case 'host':
      return 'text-green-500'
    case 'system':
      return 'text-purple-500'
    case 'alert':
      return 'text-red-500'
    case 'notification':
      return 'text-yellow-500'
    case 'user':
      return 'text-cyan-500'
    default:
      return 'text-muted-foreground'
  }
}

/**
 * Format relative time (e.g., "2 minutes ago", "1 hour ago")
 */
export function formatRelativeTime(timestamp: string): string {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return '-'

  // Return ISO date format YYYY-MM-DD
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
