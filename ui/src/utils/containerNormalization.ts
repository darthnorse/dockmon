/**
 * Container ID Normalization Utilities
 *
 * CRITICAL: All container IDs must be normalized to 12-char short IDs before reaching components.
 * This prevents mismatches between different data sources (API, WebSocket, etc.).
 *
 * Architecture:
 * - Backend always uses and returns 12-char short IDs
 * - Frontend normalizes at data boundaries (React Query, WebSocket handlers)
 * - Components never see 64-char IDs
 */

/**
 * Minimal container interface for normalization
 */
interface ContainerLike {
  id: string
  short_id?: string
}

/**
 * Normalize a single container ID to 12-char short format
 */
export function normalizeContainerId(id: string): string {
  return id.slice(0, 12)
}

/**
 * Normalize all ID fields in a container object
 *
 * Ensures consistency by truncating:
 * - container.id (primary key)
 * - container.short_id (if present)
 */
export function normalizeContainer<T extends ContainerLike>(container: T): T {
  const needsIdNorm = container.id.length > 12
  const needsShortIdNorm = container.short_id != null && container.short_id.length > 12

  // Skip cloning if IDs are already 12-char — avoids 70+ object spreads per WS message
  if (!needsIdNorm && !needsShortIdNorm) return container

  const normalized: T = {
    ...container,
    id: needsIdNorm ? normalizeContainerId(container.id) : container.id,
  }

  if (needsShortIdNorm) {
    normalized.short_id = normalizeContainerId(container.short_id!)
  }

  return normalized
}

/**
 * Normalize an array of containers
 */
export function normalizeContainers<T extends ContainerLike>(containers: T[]): T[] {
  return containers.map(normalizeContainer)
}

/**
 * Dev-mode validation: warn if a container has a 64-char ID
 * This helps catch regressions during development
 */
export function validateContainerId(id: string, context: string): void {
  if (import.meta.env.DEV && id && id.length > 12) {
    console.warn(
      `[Container ID Validation] Long container ID detected in ${context}:`,
      id,
      '\nThis should have been normalized at the data boundary.'
    )
  }
}

/**
 * Dev-mode validation for container objects
 */
export function validateContainer(container: ContainerLike, context: string): void {
  if (import.meta.env.DEV) {
    validateContainerId(container.id, `${context} - container.id`)
    if (container.short_id) {
      validateContainerId(container.short_id, `${context} - container.short_id`)
    }
  }
}
