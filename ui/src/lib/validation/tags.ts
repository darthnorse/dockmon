/**
 * Tag Validation Utilities
 *
 * Centralized validation logic for container tags.
 * Ensures consistent validation across the application.
 */

export interface TagValidationResult {
  valid: boolean
  error?: string
}

/**
 * Validate a single tag
 *
 * Rules:
 * - Must be 1-24 characters after trimming
 * - Only alphanumeric, dash, underscore, colon, and dot allowed
 * - Optional: check for duplicates against existing tags
 */
export function validateTag(
  tag: string,
  existingTags?: string[]
): TagValidationResult {
  const trimmed = tag.trim()

  if (!trimmed) {
    return { valid: false, error: 'Tag cannot be empty' }
  }

  if (trimmed.length < 1 || trimmed.length > 24) {
    return { valid: false, error: 'Tag must be 1-24 characters' }
  }

  // Allow alphanumeric + dash, underscore, colon, dot
  const validPattern = /^[a-zA-Z0-9\-_:.]+$/
  if (!validPattern.test(trimmed)) {
    return { valid: false, error: 'Invalid characters (alphanumeric, -, _, :, . only)' }
  }

  // Check for duplicates if existing tags provided
  if (existingTags) {
    const normalizedTag = trimmed.toLowerCase()
    if (existingTags.map(t => t.toLowerCase()).includes(normalizedTag)) {
      return { valid: false, error: 'Duplicate tag' }
    }
  }

  return { valid: true }
}

/**
 * Normalize a tag (trim and lowercase)
 */
export function normalizeTag(tag: string): string {
  return tag.trim().toLowerCase()
}

/**
 * Check if a tag is a derived tag (from docker-compose or swarm)
 */
export function isDerivedTag(tag: string): boolean {
  return tag.startsWith('compose:') || tag.startsWith('swarm:')
}

/**
 * Validate tag suggestions response from API
 */
export function validateTagSuggestionsResponse(data: unknown): string[] {
  if (!data || typeof data !== 'object') {
    return []
  }

  const response = data as Record<string, unknown>
  if (!Array.isArray(response.tags)) {
    return []
  }

  // Filter out non-string values and empty strings
  return response.tags.filter(
    (tag): tag is string => typeof tag === 'string' && tag.trim().length > 0
  )
}
