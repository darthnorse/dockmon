/**
 * Port conflict validation for stack deploys.
 *
 * Calls POST /stacks/{stackName}/validate-ports on host/stack change and
 * on-demand (via the returned `recheck` async function) just before submit.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '@/lib/api/client'

import type { PortConflict, ValidatePortsResponse } from '../types'

interface UsePortConflictsArgs {
  stackName: string | null
  hostId: string | null
}

interface UsePortConflictsResult {
  conflicts: PortConflict[]
  isLoading: boolean
  error: Error | null
  recheck: () => Promise<PortConflict[]>
}

const QUERY_KEY_ROOT = 'port-conflicts' as const
const EMPTY_CONFLICTS: readonly PortConflict[] = Object.freeze([])

async function fetchConflicts(stackName: string, hostId: string): Promise<PortConflict[]> {
  const data = await apiClient.post<ValidatePortsResponse>(
    `/stacks/${encodeURIComponent(stackName)}/validate-ports`,
    { host_id: hostId },
  )
  return data.conflicts
}

export function usePortConflicts({ stackName, hostId }: UsePortConflictsArgs): UsePortConflictsResult {
  const queryClient = useQueryClient()
  const enabled = Boolean(stackName && hostId)

  const query = useQuery({
    queryKey: [QUERY_KEY_ROOT, stackName, hostId],
    queryFn: () => fetchConflicts(stackName!, hostId!),
    enabled,
    staleTime: 0,
    retry: 1,
  })

  const recheck = async (): Promise<PortConflict[]> => {
    if (!stackName || !hostId) return []
    return queryClient.fetchQuery({
      queryKey: [QUERY_KEY_ROOT, stackName, hostId],
      queryFn: () => fetchConflicts(stackName, hostId),
      staleTime: 0,
    })
  }

  return {
    conflicts: query.data ?? (EMPTY_CONFLICTS as PortConflict[]),
    isLoading: query.isLoading,
    error: query.error,
    recheck,
  }
}
