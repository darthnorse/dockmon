/**
 * Container Updates Hook
 *
 * Provides hooks for checking and managing container updates
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type { ContainerUpdateStatus } from '../types'

/**
 * Hook to get update status for a container
 */
export function useContainerUpdateStatus(hostId: string | undefined, containerId: string | undefined) {
  return useQuery({
    queryKey: ['container-update-status', hostId, containerId],
    queryFn: async () => {
      if (!hostId || !containerId) {
        return null
      }

      try {
        return await apiClient.get<ContainerUpdateStatus>(
          `/hosts/${hostId}/containers/${containerId}/update-status`
        )
      } catch (error) {
        // If no update status exists yet, return a default "no data" state instead of erroring
        console.warn('No update status found for container:', containerId, error)
        return {
          update_available: false,
          current_image: null,
          current_digest: null,
          latest_image: null,
          latest_digest: null,
          floating_tag_mode: 'exact' as const,
          last_checked_at: null,
        }
      }
    },
    enabled: !!hostId && !!containerId,
    // Completely disable automatic refetching - only manual via "Check Now" button
    refetchInterval: false,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
    retry: false, // Don't retry on error
  })
}

/**
 * Hook to manually trigger update check for a container
 */
export function useCheckContainerUpdate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ hostId, containerId }: { hostId: string; containerId: string }) => {
      return await apiClient.post<ContainerUpdateStatus>(
        `/hosts/${hostId}/containers/${containerId}/check-update`
      )
    },
    onSuccess: (_data, variables) => {
      // Invalidate the update status query to refetch
      queryClient.invalidateQueries({
        queryKey: ['container-update-status', variables.hostId, variables.containerId],
      })
    },
  })
}

/**
 * Hook to trigger global update check for all containers
 */
export function useCheckAllUpdates() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => {
      return await apiClient.post<{
        total: number
        checked: number
        updates_found: number
        errors: number
      }>('/updates/check-all')
    },
    onSuccess: () => {
      // Invalidate all update status queries
      queryClient.invalidateQueries({
        queryKey: ['container-update-status'],
      })
    },
  })
}

/**
 * Hook to update auto-update configuration for a container
 */
export function useUpdateAutoUpdateConfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      hostId,
      containerId,
      autoUpdateEnabled,
      floatingTagMode,
      changelogUrl,
      registryPageUrl,
    }: {
      hostId: string
      containerId: string
      autoUpdateEnabled: boolean
      floatingTagMode: 'exact' | 'patch' | 'minor' | 'latest'
      changelogUrl?: string | null  // v2.0.2+
      registryPageUrl?: string | null  // v2.0.2+
    }) => {
      return await apiClient.put<ContainerUpdateStatus>(
        `/hosts/${hostId}/containers/${containerId}/auto-update-config`,
        {
          auto_update_enabled: autoUpdateEnabled,
          floating_tag_mode: floatingTagMode,
          changelog_url: changelogUrl,  // v2.0.2+
          registry_page_url: registryPageUrl,  // v2.0.2+
        }
      )
    },
    onSuccess: (_data, variables) => {
      // Invalidate the update status query to refetch
      queryClient.invalidateQueries({
        queryKey: ['container-update-status', variables.hostId, variables.containerId],
      })
    },
  })
}

/**
 * Hook to manually execute an update for a container
 */
export function useExecuteUpdate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      hostId,
      containerId,
      force = false
    }: {
      hostId: string
      containerId: string
      force?: boolean
    }) => {
      const params = force ? { force: 'true' } : {}
      return await apiClient.post<{
        status: string
        message: string
        previous_image: string
        new_image: string
        validation?: 'allow' | 'warn' | 'block'
        reason?: string
        matched_pattern?: string
        detail?: string  // v2.0.2+ - Detailed error message for failed updates
      }>(`/hosts/${hostId}/containers/${containerId}/execute-update`, null, { params })
    },
    onSuccess: (_data, variables) => {
      // Invalidate update status query to refetch new status
      queryClient.invalidateQueries({
        queryKey: ['container-update-status', variables.hostId, variables.containerId],
      })
      // Don't invalidate containers list - it will update automatically via WebSocket events
      // Invalidating here causes the modal to close during the update
    },
  })
}

/**
 * Hook to get updates summary (count of containers with updates available)
 */
export function useUpdatesSummary() {
  return useQuery({
    queryKey: ['updates-summary'],
    queryFn: async () => {
      return await apiClient.get<{
        total_updates: number
        containers_with_updates: string[]
      }>('/updates/summary')
    },
    staleTime: 30000, // Cache for 30s
    refetchInterval: 60000, // Refresh every minute
  })
}

/**
 * Hook to get all auto-update configurations for all containers (batch endpoint)
 *
 * Performance optimization: Single API call instead of N individual calls.
 * Used for filtering and displaying policy icons in container table.
 */
export function useAllAutoUpdateConfigs() {
  return useQuery({
    queryKey: ['all-auto-update-configs'],
    queryFn: async () => {
      return await apiClient.get<Record<string, {
        auto_update_enabled: boolean
        floating_tag_mode: string
      }>>('/auto-update-configs')
    },
    staleTime: 30000, // Cache for 30s
    refetchInterval: 60000, // Refresh every minute
  })
}

/**
 * Hook to get all health check configurations for all containers (batch endpoint)
 *
 * Performance optimization: Single API call instead of N individual calls.
 * Used for filtering and displaying policy icons in container table.
 */
export function useAllHealthCheckConfigs() {
  return useQuery({
    queryKey: ['all-health-check-configs'],
    queryFn: async () => {
      return await apiClient.get<Record<string, {
        enabled: boolean
        current_status: string
        consecutive_failures: number
      }>>('/health-check-configs')
    },
    staleTime: 30000, // Cache for 30s
    refetchInterval: 60000, // Refresh every minute
  })
}

/**
 * Hook to get all deployment metadata for all containers (batch endpoint)
 *
 * Performance optimization: Single API call instead of N individual calls.
 * Used for displaying deployment information in container table.
 * Part of deployment v2.1 remediation (Phase 1.4).
 */
export function useAllDeploymentMetadata() {
  return useQuery({
    queryKey: ['all-deployment-metadata'],
    queryFn: async () => {
      return await apiClient.get<Record<string, {
        container_id: string
        host_id: string
        deployment_id: string | null
        is_managed: boolean
        service_name: string | null
        created_at: string
        updated_at: string
      }>>('/deployment-metadata')
    },
    staleTime: 30000, // Cache for 30s
    refetchInterval: 60000, // Refresh every minute
  })
}
