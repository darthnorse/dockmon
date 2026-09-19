import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type { CapabilitiesResponse } from '@/types/roles'

const CAPABILITIES_QUERY_KEY = ['capabilities']

export function useCapabilities() {
  return useQuery({
    queryKey: CAPABILITIES_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<CapabilitiesResponse>('/v2/capabilities')
      return response
    },
    staleTime: Infinity, // Capabilities never change at runtime - cache indefinitely
    gcTime: Infinity,
  })
}
