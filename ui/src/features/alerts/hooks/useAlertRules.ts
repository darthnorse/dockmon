/**
 * React Query hooks for Alert Rules API
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type { AlertRule, AlertRuleRequest } from '@/types/alerts'

const API_BASE = '/alerts/rules'

// Fetch all alert rules
export function useAlertRules() {
  return useQuery<{ rules: AlertRule[]; total: number }>({
    queryKey: ['alert-rules'],
    queryFn: async () => {
      return apiClient.get<{ rules: AlertRule[]; total: number }>(API_BASE)
    },
  })
}

// Fetch single alert rule
export function useAlertRule(ruleId: string | null) {
  return useQuery<AlertRule>({
    queryKey: ['alert-rule', ruleId],
    queryFn: async () => {
      if (!ruleId) throw new Error('Rule ID required')
      return apiClient.get<AlertRule>(`${API_BASE}/${ruleId}`)
    },
    enabled: !!ruleId,
  })
}

// Create alert rule mutation
export function useCreateAlertRule() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (rule: AlertRuleRequest) => {
      return apiClient.post<AlertRule>(API_BASE, rule)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    },
  })
}

// Update alert rule mutation
export function useUpdateAlertRule() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ ruleId, rule }: { ruleId: string; rule: AlertRuleRequest }) => {
      return apiClient.put<AlertRule>(`${API_BASE}/${ruleId}`, rule)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    },
  })
}

// Delete alert rule mutation
export function useDeleteAlertRule() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (ruleId: string) => {
      return apiClient.delete<{ success: boolean }>(`${API_BASE}/${ruleId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    },
  })
}

// Toggle alert rule enabled state
export function useToggleAlertRule() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ ruleId, enabled }: { ruleId: string; enabled: boolean }) => {
      return apiClient.patch<AlertRule>(`${API_BASE}/${ruleId}/toggle`, { enabled })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    },
  })
}
