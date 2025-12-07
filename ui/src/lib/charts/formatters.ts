/**
 * Chart value and time formatting utilities
 */

/**
 * Format bytes into human-readable units (B, KB, MB, GB, TB)
 * @param bytes - Number of bytes
 * @param decimals - Number of decimal places (default: 1)
 * @returns Formatted string like "2.1 GB" or "512 MB"
 */
export function formatBytes(bytes: number, decimals: number = 1): string {
  if (bytes === 0) return '0 B'

  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  const value = bytes / Math.pow(k, i)
  return `${value.toFixed(decimals)} ${sizes[i]}`
}

/**
 * Format relative time from seconds ago
 * For axis labels, we round to nearest minute when >= 60s for cleaner display
 * @param secondsAgo - Number of seconds in the past
 * @returns Formatted string like "2m", "45s", "now"
 */
export function formatRelativeTime(secondsAgo: number): string {
  if (secondsAgo < 1) return 'now'

  // If less than 60 seconds, show as seconds
  if (secondsAgo < 60) {
    return `${Math.floor(secondsAgo)}s`
  }

  // Round UP to show the time range (e.g., 87s shows as "2m" not "1m")
  // This gives better context about how much history is available
  const minutes = Math.ceil(secondsAgo / 60)
  return `${minutes}m`
}

/**
 * Format CPU percentage value
 * @param value - CPU percentage (0-100)
 * @returns Formatted string like "45.2%"
 */
export function formatCpuValue(value: number): string {
  return `${value.toFixed(1)}%`
}

/**
 * Format memory percentage value with optional byte display
 * @param value - Memory percentage (0-100)
 * @param bytes - Optional memory in bytes
 * @returns Formatted string like "67.8%" or "67.8% (2.1 GB)"
 */
export function formatMemValue(value: number, bytes?: number): string {
  const percentage = value.toFixed(1)
  if (bytes !== undefined && bytes > 0) {
    return `${percentage}% (${formatBytes(bytes)})`
  }
  return `${percentage}%`
}

/**
 * Format network throughput value
 * @param bytesPerSec - Network bytes per second
 * @returns Formatted string like "12.5 MB/s"
 */
export function formatNetValue(bytesPerSec: number): string {
  return `${formatBytes(bytesPerSec)}/s`
}

/**
 * Format Y-axis values based on metric type
 * @param value - Raw value
 * @param isPercentage - Whether this is a percentage metric (CPU/Memory)
 * @returns Formatted string for axis label
 */
export function formatYAxisValue(value: number, isPercentage: boolean): string {
  if (isPercentage) {
    // For percentages, show whole numbers for cleaner axis
    return `${Math.round(value)}%`
  }
  // For network (bytes/sec), format with units and /s suffix
  if (value === 0) return '0 B/s'

  const k = 1024
  const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
  const i = Math.floor(Math.log(value) / Math.log(k))
  const formattedValue = value / Math.pow(k, i)

  // For axis labels, use minimal decimals
  if (formattedValue >= 100) {
    return `${Math.round(formattedValue)} ${sizes[i]}`
  } else if (formattedValue >= 10) {
    return `${formattedValue.toFixed(0)} ${sizes[i]}`
  } else {
    return `${formattedValue.toFixed(1)} ${sizes[i]}`
  }
}
