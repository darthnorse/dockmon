/**
 * Agent API Hooks for DockMon v2.2.0
 *
 * TanStack Query hooks for agent management operations
 */

import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import type {
  RegistrationTokenResponse,
  AgentListResponse,
  AgentStatusResponse,
} from '../types'

const API_BASE = '/api'

/**
 * Generate a registration token for agent installation
 */
export function useGenerateToken() {
  return useMutation({
    mutationFn: async (options?: { multiUse?: boolean }): Promise<RegistrationTokenResponse> => {
      const response = await fetch(`${API_BASE}/agent/generate-token`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ multi_use: options?.multiUse ?? false }),
      })

      if (!response.ok) {
        const error = await response.text()
        throw new Error(error || 'Failed to generate token')
      }

      return response.json()
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
      const response = await fetch(`${API_BASE}/agent/list`, {
        credentials: 'include',
      })

      if (!response.ok) {
        throw new Error(`Failed to fetch agents: ${response.statusText}`)
      }

      return response.json()
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

      const response = await fetch(`${API_BASE}/agent/${agentId}/status`, {
        credentials: 'include',
      })

      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Agent not found')
        }
        throw new Error(`Failed to fetch agent status: ${response.statusText}`)
      }

      return response.json()
    },
    enabled: !!agentId,
    // Refetch every 5 seconds for individual agent status
    refetchInterval: 5000,
  })
}
