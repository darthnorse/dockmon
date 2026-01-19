/**
 * Image utility functions
 */

import type { DockerImage } from '@/types/api'

/**
 * Get display name for an image (first tag or ID)
 *
 * @example
 * getImageDisplayName({ tags: ['nginx:latest'], id: 'abc123' }) // 'nginx:latest'
 * getImageDisplayName({ tags: [], id: 'abc123' }) // '<none>:abc123'
 */
export function getImageDisplayName(image: DockerImage): string {
  const firstTag = image.tags[0]
  if (firstTag) {
    return firstTag
  }
  return `<none>:${image.id}`
}

/**
 * Make composite key for image (hostId:imageId)
 *
 * @example
 * makeImageCompositeKey('host-123', 'abc123def456') // 'host-123:abc123def456'
 */
export function makeImageCompositeKey(hostId: string, imageId: string): string {
  return `${hostId}:${imageId}`
}
