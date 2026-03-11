/**
 * Formatting Utilities
 *
 * Shared formatting functions for displaying data in human-readable formats
 */

/**
 * Format bytes to human-readable format with appropriate units
 *
 * @param bytes - Size in bytes (can be null/undefined)
 * @returns Formatted string with units: "256.0 MB", "2.41 GB", etc.
 *
 * @example
 * formatBytes(256 * 1024 * 1024) // "256.0 MB"
 * formatBytes(2.41 * 1024 * 1024 * 1024) // "2.41 GB"
 * formatBytes(512 * 1024) // "512.0 KB"
 * formatBytes(null) // "0 B"
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes < 0 || !isFinite(bytes)) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1)

  // Use appropriate decimal precision based on unit
  const decimals = i === 0 ? 0 : i >= 3 ? 2 : 1 // B: 0, KB/MB: 1, GB/TB: 2

  return `${(bytes / Math.pow(k, i)).toFixed(decimals)} ${sizes[i]}`
}

/**
 * Format a network rate (bytes per second) to human-readable format
 *
 * @param bytesPerSec - Network rate in bytes per second (can be null/undefined)
 * @returns Formatted string with rate units: "1.5 KB/s", "3.20 MB/s", etc.
 *
 * @example
 * formatNetworkRate(1500) // "1.5 KB/s"
 * formatNetworkRate(2.5 * 1024 * 1024) // "2.50 MB/s"
 * formatNetworkRate(null) // "0 B/s"
 */
export function formatNetworkRate(bytesPerSec: number | null | undefined): string {
  if (!bytesPerSec) return '0 B/s'
  return formatBytes(bytesPerSec) + '/s'
}

/**
 * Format memory bytes to compact format (backwards compatibility)
 *
 * @deprecated Use formatBytes() instead for consistent formatting
 * @param bytes - Memory size in bytes
 * @returns Formatted string: "256MB" for <1GB, "2.41GB" for >=1GB
 */
export function formatMemory(bytes: number): string {
  const mb = bytes / (1024 * 1024)
  if (mb < 1024) return `${mb.toFixed(0)}MB`
  const gb = mb / 1024
  return `${gb.toFixed(2)}GB`
}

/**
 * Pluralize a word based on count
 *
 * @param count - The count to check
 * @param singular - Singular form of the word
 * @param plural - Optional plural form (defaults to singular + 's')
 * @returns The appropriate form based on count
 *
 * @example
 * pluralize(1, 'image') // "image"
 * pluralize(5, 'image') // "images"
 * pluralize(0, 'container') // "containers"
 * pluralize(2, 'entry', 'entries') // "entries"
 */
export function pluralize(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : (plural ?? singular + 's')
}

/**
 * Format a daemon start timestamp into a human-readable uptime string.
 *
 * @param daemonStartedAt - ISO timestamp of when the Docker daemon started
 * @returns Formatted uptime: "5d 3h", "2h 15m", "42m", or null if unavailable
 */
export function formatUptime(daemonStartedAt?: string | null): string | null {
  if (!daemonStartedAt) return null

  try {
    const startTime = new Date(daemonStartedAt)
    const now = new Date()
    const diffMs = now.getTime() - startTime.getTime()
    if (diffMs < 0) return null

    const days = Math.floor(diffMs / (1000 * 60 * 60 * 24))
    const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))

    if (days > 0) return `${days}d ${hours}h`
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m`
  } catch {
    return null
  }
}
