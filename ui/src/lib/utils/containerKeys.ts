/**
 * Container Key Utilities
 *
 * CRITICAL: Composite key format for multi-host container identification.
 * Prevents collisions when multiple hosts have containers with same SHORT IDs
 * (e.g., cloned LXC VMs with identical container IDs).
 *
 * Format: {host_id}:{container_id}
 * Example: "f07d655f-ce9a-4da8-a7a3-7ac6e15a9efb:abc123def456"
 *
 * See CLAUDE.md: "ALWAYS use composite keys for any container-related storage/lookups"
 */

import type { Container } from '@/features/containers/types'

/**
 * Create composite key from Container object
 *
 * @param container - Container-like object with host_id and id
 * @returns Composite key in format "{host_id}:{container_id}"
 *
 * @example
 * const container = { host_id: "host-123", id: "abc123", ... }
 * makeCompositeKey(container) // "host-123:abc123"
 */
export function makeCompositeKey(container: Pick<Container, 'host_id' | 'id'>): string {
  return `${container.host_id}:${container.id}`
}

/**
 * Create composite key from separate host ID and container ID
 *
 * @param hostId - Host UUID
 * @param containerId - Container SHORT ID (12 chars)
 * @returns Composite key in format "{host_id}:{container_id}"
 *
 * @example
 * makeCompositeKeyFrom("host-123", "abc123") // "host-123:abc123"
 */
export function makeCompositeKeyFrom(hostId: string, containerId: string): string {
  return `${hostId}:${containerId}`
}

/**
 * Parse composite key into host ID and container ID components
 *
 * @param compositeKey - Composite key in format "{host_id}:{container_id}"
 * @returns Object with hostId and containerId
 *
 * @example
 * parseCompositeKey("host-123:abc123")
 * // { hostId: "host-123", containerId: "abc123" }
 */
export function parseCompositeKey(compositeKey: string): { hostId: string; containerId: string } {
  const [hostId = '', containerId = ''] = compositeKey.split(':')
  return { hostId, containerId }
}
