/**
 * useAuditLog Hook
 * Manages Audit Log operations with React Query
 *
 * Phase 6 of Multi-User Support (v2.3.0)
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type {
  AuditLogListResponse,
  AuditLogQueryParams,
  AuditLogStatsResponse,
  AuditLogUser,
  RetentionSettingsResponse,
  UpdateRetentionRequest,
  RetentionUpdateResponse,
  CleanupResponse,
} from '@/types/audit'
import { toast } from 'sonner'

// =============================================================================
// Constants
// =============================================================================

const AUDIT_LOG_QUERY_KEY = ['audit-log']

// Stale times in milliseconds
const STALE_TIME = {
  LIST: 10 * 1000,        // 10 seconds - entries change frequently
  USERS: 30 * 1000,       // 30 seconds - user list is fairly stable
  STATS: 30 * 1000,       // 30 seconds - stats update moderately
  RETENTION: 60 * 1000,   // 1 minute - retention rarely changes
  STATIC: Infinity,       // Actions/entity-types never change at runtime
} as const

// =============================================================================
// Helpers
// =============================================================================

/**
 * Build query params object from AuditLogQueryParams, filtering out undefined values.
 */
function buildQueryParams(params: AuditLogQueryParams): Record<string, string> {
  const result: Record<string, string> = {}

  if (params.page !== undefined) result.page = String(params.page)
  if (params.page_size !== undefined) result.page_size = String(params.page_size)
  if (params.user_id !== undefined) result.user_id = String(params.user_id)
  if (params.username) result.username = params.username
  if (params.action) result.action = params.action
  if (params.entity_type) result.entity_type = params.entity_type
  if (params.entity_id) result.entity_id = params.entity_id
  if (params.search) result.search = params.search
  if (params.start_date) result.start_date = params.start_date
  if (params.end_date) result.end_date = params.end_date

  return result
}

/**
 * Build URLSearchParams from AuditLogQueryParams for export endpoint.
 */
function buildExportParams(params: AuditLogQueryParams): URLSearchParams {
  const searchParams = new URLSearchParams()

  if (params.user_id !== undefined) searchParams.set('user_id', String(params.user_id))
  if (params.username) searchParams.set('username', params.username)
  if (params.action) searchParams.set('action', params.action)
  if (params.entity_type) searchParams.set('entity_type', params.entity_type)
  if (params.start_date) searchParams.set('start_date', params.start_date)
  if (params.end_date) searchParams.set('end_date', params.end_date)

  return searchParams
}

// =============================================================================
// Query Hooks
// =============================================================================

/**
 * Fetch audit log entries with filtering and pagination
 */
export function useAuditLog(params: AuditLogQueryParams = {}) {
  const queryParams = buildQueryParams(params)

  return useQuery({
    queryKey: [...AUDIT_LOG_QUERY_KEY, 'list', queryParams],
    queryFn: () => apiClient.get<AuditLogListResponse>('/v2/audit-log', { params: queryParams }),
    staleTime: STALE_TIME.LIST,
  })
}

/**
 * Fetch available audit actions (static data)
 */
export function useAuditActions() {
  return useQuery({
    queryKey: [...AUDIT_LOG_QUERY_KEY, 'actions'],
    queryFn: () => apiClient.get<string[]>('/v2/audit-log/actions'),
    staleTime: STALE_TIME.STATIC,
  })
}

/**
 * Fetch available audit entity types (static data)
 */
export function useAuditEntityTypes() {
  return useQuery({
    queryKey: [...AUDIT_LOG_QUERY_KEY, 'entity-types'],
    queryFn: () => apiClient.get<string[]>('/v2/audit-log/entity-types'),
    staleTime: STALE_TIME.STATIC,
  })
}

/**
 * Fetch users who have audit log entries
 */
export function useAuditUsers() {
  return useQuery({
    queryKey: [...AUDIT_LOG_QUERY_KEY, 'users'],
    queryFn: () => apiClient.get<AuditLogUser[]>('/v2/audit-log/users'),
    staleTime: STALE_TIME.USERS,
  })
}

/**
 * Fetch audit log statistics
 */
export function useAuditStats() {
  return useQuery({
    queryKey: [...AUDIT_LOG_QUERY_KEY, 'stats'],
    queryFn: () => apiClient.get<AuditLogStatsResponse>('/v2/audit-log/stats'),
    staleTime: STALE_TIME.STATS,
  })
}

/**
 * Fetch retention settings
 */
export function useAuditRetention() {
  return useQuery({
    queryKey: [...AUDIT_LOG_QUERY_KEY, 'retention'],
    queryFn: () => apiClient.get<RetentionSettingsResponse>('/v2/audit-log/retention'),
    staleTime: STALE_TIME.RETENTION,
  })
}

// =============================================================================
// Mutation Hooks
// =============================================================================

/**
 * Update retention settings
 */
export function useUpdateAuditRetention() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (request: UpdateRetentionRequest) =>
      apiClient.put<RetentionUpdateResponse>('/v2/audit-log/retention', request),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: AUDIT_LOG_QUERY_KEY })
      toast.success(response.message)
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to update retention settings')
    },
  })
}

/**
 * Manually trigger audit log cleanup
 */
export function useCleanupAuditLog() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => apiClient.post<CleanupResponse>('/v2/audit-log/cleanup'),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: AUDIT_LOG_QUERY_KEY })
      toast.success(response.message)
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to cleanup audit log')
    },
  })
}

/**
 * Export audit log to CSV
 *
 * Uses raw fetch() instead of apiClient because we need to handle blob response
 * and access custom headers for truncation info. apiClient is designed for JSON.
 */
export function useExportAuditLog() {
  return useMutation({
    mutationFn: async (params: AuditLogQueryParams = {}) => {
      const searchParams = buildExportParams(params)
      const queryString = searchParams.toString()
      const url = `/v2/audit-log/export${queryString ? `?${queryString}` : ''}`

      const response = await fetch(`/api${url}`, { credentials: 'include' })

      if (!response.ok) {
        throw new Error('Failed to export audit log')
      }

      // Check truncation headers
      const isTruncated = response.headers.get('X-Export-Truncated') === 'true'
      const totalMatching = response.headers.get('X-Export-Total-Matching')
      const included = response.headers.get('X-Export-Included')

      // Extract filename from Content-Disposition
      const contentDisposition = response.headers.get('Content-Disposition')
      let filename = 'audit_log.csv'
      if (contentDisposition) {
        const match = contentDisposition.match(/filename=([^;]+)/)
        if (match && match[1]) {
          filename = match[1].replace(/"/g, '')
        }
      }

      // Trigger download
      const blob = await response.blob()
      const downloadUrl = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = downloadUrl
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(downloadUrl)

      return {
        success: true,
        filename,
        isTruncated,
        totalMatching: totalMatching ? parseInt(totalMatching, 10) : null,
        included: included ? parseInt(included, 10) : null,
      }
    },
    onSuccess: ({ filename, isTruncated, totalMatching, included }) => {
      if (isTruncated && totalMatching && included) {
        toast.warning(
          `Export truncated: ${included.toLocaleString()} of ${totalMatching.toLocaleString()} entries. Use date filters for specific ranges.`,
          { duration: 6000 }
        )
      } else {
        toast.success(`Exported to ${filename}`)
      }
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to export audit log')
    },
  })
}
