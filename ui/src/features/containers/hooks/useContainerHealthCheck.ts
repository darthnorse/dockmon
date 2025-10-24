/**
 * Container HTTP Health Check Hook
 *
 * Provides hooks for managing container HTTP/HTTPS health checks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type { ContainerHttpHealthCheck } from '../types'

/**
 * Hook to get HTTP health check configuration for a container
 */
export function useContainerHealthCheck(hostId: string | undefined, containerId: string | undefined) {
  return useQuery({
    queryKey: ['container-health-check', hostId, containerId],
    queryFn: async () => {
      if (!hostId || !containerId) {
        return null
      }

      try {
        return await apiClient.get<ContainerHttpHealthCheck>(
          `/containers/${hostId}/${containerId}/http-health-check`
        )
      } catch (error) {
        // If no health check exists yet, return a default state
        console.warn('No health check found for container:', containerId, error)
        return {
          enabled: false,
          url: '',
          method: 'GET',
          expected_status_codes: '200',
          timeout_seconds: 10,
          check_interval_seconds: 60,
          follow_redirects: true,
          verify_ssl: true,
          headers_json: null,
          auth_config_json: null,
          current_status: 'unknown' as const,
          last_checked_at: null,
          last_success_at: null,
          last_failure_at: null,
          consecutive_successes: null,  // null = no record exists
          consecutive_failures: null,   // null = no record exists
          last_response_time_ms: null,
          last_error_message: null,
          auto_restart_on_failure: false,
          failure_threshold: 3,
          success_threshold: 1,
          max_restart_attempts: 3,  // v2.0.2+
          restart_retry_delay_seconds: 120,  // v2.0.2+
        }
      }
    },
    enabled: !!hostId && !!containerId,
    refetchInterval: (query) => {
      // Auto-refresh based on check interval (minimum 10s, maximum check interval)
      if (!query.state.data?.enabled) return false
      const checkIntervalSeconds = query.state.data.check_interval_seconds || 60
      // Poll at the same interval as the backend check, with a minimum of 10s
      return Math.max(checkIntervalSeconds * 1000, 10000)
    },
    staleTime: 5000,
  })
}

/**
 * Hook to update HTTP health check configuration for a container
 */
export function useUpdateHealthCheck() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      hostId,
      containerId,
      config,
    }: {
      hostId: string
      containerId: string
      config: Partial<ContainerHttpHealthCheck>
    }) => {
      return await apiClient.put<ContainerHttpHealthCheck>(
        `/containers/${hostId}/${containerId}/http-health-check`,
        config
      )
    },
    onSuccess: (_data, variables) => {
      // Invalidate the health check query to refetch
      queryClient.invalidateQueries({
        queryKey: ['container-health-check', variables.hostId, variables.containerId],
      })
    },
  })
}

/**
 * Hook to delete HTTP health check configuration for a container
 */
export function useDeleteHealthCheck() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ hostId, containerId }: { hostId: string; containerId: string }) => {
      return await apiClient.delete(`/containers/${hostId}/${containerId}/http-health-check`)
    },
    onSuccess: (_data, variables) => {
      // Invalidate the health check query to refetch
      queryClient.invalidateQueries({
        queryKey: ['container-health-check', variables.hostId, variables.containerId],
      })
    },
  })
}

/**
 * Test result from health check test endpoint
 */
export interface HealthCheckTestResult {
  status_code: number | null
  response_time_ms: number
  is_healthy: boolean
  message: string
}

/**
 * Hook to test HTTP health check configuration without saving
 */
export function useTestHealthCheck() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      hostId,
      containerId,
      config,
    }: {
      hostId: string
      containerId: string
      config: Partial<ContainerHttpHealthCheck>
    }) => {
      const response = await apiClient.post<{ success: boolean; test_result: HealthCheckTestResult }>(
        `/containers/${hostId}/${containerId}/http-health-check/test`,
        config
      )
      return response.test_result
    },
    onSuccess: (_data, variables) => {
      // Invalidate the health check query to refetch updated status
      queryClient.invalidateQueries({
        queryKey: ['container-health-check', variables.hostId, variables.containerId],
      })
    },
  })
}
