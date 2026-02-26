/**
 * Agent API Hooks for DockMon v2.2.0
 *
 * TanStack Query hooks for agent management operations
 */

import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import type {
  RegistrationTokenResponse,
  AgentListResponse,
  AgentStatusResponse,
} from '../types'

/**
 * Generate a registration token for agent installation
 */
export function useGenerateToken() {
  return useMutation({
    mutationFn: async (options?: { multiUse?: boolean }): Promise<RegistrationTokenResponse> => {
      try {
        const response = await apiClient.post<RegistrationTokenResponse>('/agent/generate-token', {
          multi_use: options?.multiUse ?? false
        })
        return response
      } catch (error: any) {
        throw new Error(error.data?.detail || error.message || 'Failed to generate token')
      }
    },
    onSuccess: (data) => {
      const message = data.multi_use
        ? 'Multi-use registration token generated'
        : 'Registration token generated'
      toast.success(message)
    },
    onError: (error: Error) => {
      toast.error(`Failed to generate token: ${error.message}`)
    },
  })
}

/**
 * Fetch all registered agents
 */
export function useAgents() {
  return useQuery({
    queryKey: ['agents'],
    queryFn: async (): Promise<AgentListResponse> => {
      try {
        const response = await apiClient.get<AgentListResponse>('/agent/list')
        return response
      } catch (error: any) {
        throw new Error(error.data?.detail || error.message || 'Failed to fetch agents')
      }
    },
    // Refetch every 10 seconds to keep agent status up-to-date
    refetchInterval: 10000,
  })
}

/**
 * Fetch a specific agent's status
 */
export function useAgentStatus(agentId: string | null) {
  return useQuery({
    queryKey: ['agents', agentId],
    queryFn: async (): Promise<AgentStatusResponse> => {
      if (!agentId) throw new Error('Agent ID is required')

      try {
        const response = await apiClient.get<AgentStatusResponse>(`/agent/${agentId}/status`)
        return response
      } catch (error: any) {
        if (error.status === 404) {
          throw new Error('Agent not found')
        }
        throw new Error(error.data?.detail || error.message || 'Failed to fetch agent status')
      }
    },
    enabled: !!agentId,
    // Refetch every 5 seconds for individual agent status
    refetchInterval: 5000,
  })
}
