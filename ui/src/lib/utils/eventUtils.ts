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
  const date = new Date(timestamp)
  const now = new Date()
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000)

  if (diffInSeconds < 60) {
    return 'Just now'
  }

  const diffInMinutes = Math.floor(diffInSeconds / 60)
  if (diffInMinutes < 60) {
    return `${diffInMinutes} ${diffInMinutes === 1 ? 'minute' : 'minutes'} ago`
  }

  const diffInHours = Math.floor(diffInMinutes / 60)
  if (diffInHours < 24) {
    return `${diffInHours} ${diffInHours === 1 ? 'hour' : 'hours'} ago`
  }

  const diffInDays = Math.floor(diffInHours / 24)
  if (diffInDays < 7) {
    return `${diffInDays} ${diffInDays === 1 ? 'day' : 'days'} ago`
  }

  const diffInWeeks = Math.floor(diffInDays / 7)
  if (diffInWeeks < 4) {
    return `${diffInWeeks} ${diffInWeeks === 1 ? 'week' : 'weeks'} ago`
  }

  // For older events, show the date
  return date.toLocaleDateString()
}

/**
 * Format timestamp for display
 */
export function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleString()
}
