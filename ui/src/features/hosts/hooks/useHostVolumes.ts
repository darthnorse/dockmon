/**
 * useHostVolumes - TanStack Query hooks for host volumes
 *
 * FEATURES:
 * - useHostVolumes(): Fetch all volumes for a host
 */

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type { DockerVolume } from '@/types/api'

/**
 * Fetch all volumes for a host
 */
async function fetchHostVolumes(hostId: string): Promise<DockerVolume[]> {
  return await apiClient.get<DockerVolume[]>(`/hosts/${hostId}/volumes`)
}

/**
 * Hook to fetch volumes for a specific host
 */
export function useHostVolumes(hostId: string) {
  return useQuery({
    queryKey: ['host-volumes', hostId],
    queryFn: () => fetchHostVolumes(hostId),
    enabled: !!hostId,
    staleTime: 30_000, // 30 seconds
  })
}
