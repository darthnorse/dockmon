/**
 * Time Formatting Utilities
 *
 * Central utility for consistent time formatting across the app.
 * Respects user's time format preference (12h or 24h).
 */

/** Time format type - 12-hour or 24-hour clock */
export type TimeFormat = '12h' | '24h'

/** Default time format used when no preference is set */
export const DEFAULT_TIME_FORMAT: TimeFormat = '24h'

/**
 * Format a date/timestamp to a localized string respecting the user's time format preference.
 *
 * @param date - Date object, ISO string, or timestamp
 * @param timeFormat - '12h' or '24h' format preference
 * @param options - Additional formatting options
 * @returns Formatted date/time string
 */
export function formatDateTime(
  date: Date | string | number,
  timeFormat: TimeFormat = DEFAULT_TIME_FORMAT,
  options: {
    includeDate?: boolean
    includeSeconds?: boolean
    dateStyle?: 'short' | 'medium' | 'long'
  } = {}
): string {
  const { includeDate = true, includeSeconds = false, dateStyle = 'short' } = options

  const d = date instanceof Date ? date : new Date(date)

  if (isNaN(d.getTime())) {
    return 'Invalid date'
  }

  const hour12 = timeFormat === '12h'

  // Lookup for month format based on dateStyle
  const monthFormats = { long: 'long', medium: 'short', short: 'numeric' } as const

  if (includeDate) {
    // Full date and time
    return d.toLocaleString(undefined, {
      year: dateStyle === 'short' ? '2-digit' : 'numeric',
      month: monthFormats[dateStyle],
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      second: includeSeconds ? '2-digit' : undefined,
      hour12,
    })
  } else {
    // Time only
    return d.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
      second: includeSeconds ? '2-digit' : undefined,
      hour12,
    })
  }
}

/**
 * Format a date/timestamp to time only (no date).
 *
 * @param date - Date object, ISO string, or timestamp
 * @param timeFormat - '12h' or '24h' format preference
 * @param includeSeconds - Whether to include seconds
 * @returns Formatted time string
 */
export function formatTime(
  date: Date | string | number,
  timeFormat: TimeFormat = DEFAULT_TIME_FORMAT,
  includeSeconds = false
): string {
  return formatDateTime(date, timeFormat, { includeDate: false, includeSeconds })
}

/**
 * Format a timestamp for display (date + time, medium format).
 * This is the most commonly used format for event timestamps.
 *
 * @param timestamp - ISO timestamp string
 * @param timeFormat - '12h' or '24h' format preference
 * @returns Formatted timestamp string
 */
export function formatTimestamp(
  timestamp: string,
  timeFormat: TimeFormat = DEFAULT_TIME_FORMAT
): string {
  return formatDateTime(timestamp, timeFormat, { includeDate: true, dateStyle: 'medium' })
}
