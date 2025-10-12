/**
 * useTags - Hook for managing tags
 * Phase 3d Sub-Phase 5
 *
 * FEATURES:
 * - Fetch all unique tags from hosts
 * - Derived container tags (from labels) not included
 * - Used for autocomplete in TagInput
 *
 * USAGE:
 * const { tags, isLoading } = useTags()
 */

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type { Host } from '@/types/api'

/**
 * Fetch all hosts and extract unique tags
 */
async function fetchTags(): Promise<string[]> {
  const hosts = await apiClient.get<Host[]>('/hosts')

  // Extract all tags from all hosts
  const allTags = hosts
    .flatMap((host: Host) => host.tags || [])
    .filter((tag: string, index: number, self: string[]) => self.indexOf(tag) === index) // Unique
    .sort() // Alphabetical

  return allTags
}

/**
 * Hook to fetch all unique tags
 */
export function useTags() {
  const query = useQuery({
    queryKey: ['tags'],
    queryFn: fetchTags,
    staleTime: 1000 * 60 * 5, // 5 minutes (tags don't change often)
  })

  return {
    tags: query.data || [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}
