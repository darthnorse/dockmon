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
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  // Use appropriate decimal precision based on unit
  const decimals = i === 0 ? 0 : i >= 3 ? 2 : 1 // B: 0, KB/MB: 1, GB/TB: 2

  return `${(bytes / Math.pow(k, i)).toFixed(decimals)} ${sizes[i]}`
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
