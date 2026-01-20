/**
 * Batch Processing Utilities
 *
 * Shared utilities for batch operations with concurrency control
 */

import { toast } from 'sonner'
import { getErrorMessage } from './errors'
import { pluralize } from './formatting'

/**
 * Result of a batch delete operation for a single item
 */
export interface BatchDeleteResult<K extends string | number = string> {
  key: K
  success: boolean
  error?: string
}

/**
 * Execute delete operations in parallel with a concurrency limit
 *
 * @param items - Array of items to delete
 * @param deleteFn - Async function to delete a single item, returns the item key on success
 * @param getKey - Function to extract the key from an item (for result tracking)
 * @param concurrencyLimit - Maximum concurrent operations (default: 5)
 * @returns Array of results with success/failure status for each item
 *
 * @example
 * const results = await batchDeleteWithConcurrency(
 *   networks,
 *   async (network) => {
 *     await apiClient.delete(`/hosts/${hostId}/networks/${network.id}`)
 *     return network.id
 *   },
 *   (network) => network.id
 * )
 */
export async function batchDeleteWithConcurrency<T, K extends string | number = string>(
  items: T[],
  deleteFn: (item: T) => Promise<K>,
  getKey: (item: T) => K,
  concurrencyLimit: number = 5
): Promise<BatchDeleteResult<K>[]> {
  const results: BatchDeleteResult<K>[] = []

  // Process in batches
  for (let i = 0; i < items.length; i += concurrencyLimit) {
    const batch = items.slice(i, i + concurrencyLimit)
    const batchResults = await Promise.allSettled(
      batch.map((item) => deleteFn(item))
    )

    // Process batch results
    batchResults.forEach((result, idx) => {
      const item = batch[idx]!
      const key = getKey(item)
      if (result.status === 'fulfilled') {
        results.push({ key, success: true })
      } else {
        results.push({ key, success: false, error: getErrorMessage(result.reason, 'Delete failed') })
      }
    })
  }

  return results
}

/**
 * Show appropriate toast notification for bulk delete results
 *
 * @param successCount - Number of successful deletions
 * @param failCount - Number of failed deletions
 * @param entityName - Singular name of the entity (e.g., 'network', 'volume', 'image')
 *
 * @example
 * showBulkDeleteToast(5, 0, 'network')  // "Deleted 5 networks"
 * showBulkDeleteToast(3, 2, 'volume')   // "Deleted 3 volumes, 2 failed"
 * showBulkDeleteToast(0, 4, 'image')    // "Failed to delete 4 images"
 */
export function showBulkDeleteToast(
  successCount: number,
  failCount: number,
  entityName: string
): void {
  if (failCount === 0) {
    toast.success(`Deleted ${successCount} ${pluralize(successCount, entityName)}`)
  } else if (successCount > 0) {
    toast.warning(`Deleted ${successCount} ${pluralize(successCount, entityName)}, ${failCount} failed`)
  } else {
    toast.error(`Failed to delete ${failCount} ${pluralize(failCount, entityName)}`)
  }
}
