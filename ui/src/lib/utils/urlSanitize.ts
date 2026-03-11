/**
 * URL sanitization utilities to prevent XSS via javascript: URIs
 */

const ALLOWED_PROTOCOLS = ['http:', 'https:']

export function isSafeUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    return ALLOWED_PROTOCOLS.includes(parsed.protocol)
  } catch {
    return false
  }
}

export function sanitizeHref(url: string): string | undefined {
  return isSafeUrl(url) ? url : undefined
}
