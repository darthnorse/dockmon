/**
 * useGroups Hook
 * Manages Custom Groups CRUD operations with React Query
 *
 * Phase 5 of Multi-User Support (v2.3.0)
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type {
  Group,
  GroupDetail,
  GroupMember,
  GroupListResponse,
  CreateGroupRequest,
  UpdateGroupRequest,
  AddMemberRequest,
  AddMemberResponse,
  RemoveMemberResponse,
  DeleteGroupResponse,
} from '@/types/groups'
import { toast } from 'sonner'

const GROUPS_QUERY_KEY = ['groups']

/**
 * Fetch all groups (admin only)
 */
export function useGroups() {
  return useQuery({
    queryKey: GROUPS_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<GroupListResponse>('/v2/groups')
      return response
    },
    staleTime: 30 * 1000, // 30 seconds
  })
}

/**
 * Get a single group with members (admin only)
 */
export function useGroup(groupId: number | null) {
  return useQuery({
    queryKey: [...GROUPS_QUERY_KEY, groupId],
    queryFn: async () => {
      if (groupId === null) return null
      const response = await apiClient.get<GroupDetail>(`/v2/groups/${groupId}`)
      return response
    },
    enabled: groupId !== null,
    staleTime: 30 * 1000,
  })
}

/**
 * Get group members (admin only)
 */
export function useGroupMembers(groupId: number | null) {
  return useQuery({
    queryKey: [...GROUPS_QUERY_KEY, groupId, 'members'],
    queryFn: async () => {
      if (groupId === null) return []
      const response = await apiClient.get<GroupMember[]>(`/v2/groups/${groupId}/members`)
      return response
    },
    enabled: groupId !== null,
    staleTime: 30 * 1000,
  })
}

/**
 * Create a new group (admin only)
 */
export function useCreateGroup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateGroupRequest) => {
      const response = await apiClient.post<Group>('/v2/groups', request)
      return response
    },
    onSuccess: (group) => {
      queryClient.invalidateQueries({ queryKey: GROUPS_QUERY_KEY })
      toast.success(`Group "${group.name}" created successfully`)
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to create group')
    },
  })
}

/**
 * Update an existing group (admin only)
 */
export function useUpdateGroup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ groupId, request }: { groupId: number; request: UpdateGroupRequest }) => {
      const response = await apiClient.put<Group>(`/v2/groups/${groupId}`, request)
      return response
    },
    onSuccess: (group) => {
      queryClient.invalidateQueries({ queryKey: GROUPS_QUERY_KEY })
      toast.success(`Group "${group.name}" updated successfully`)
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to update group')
    },
  })
}

/**
 * Delete a group (admin only)
 */
export function useDeleteGroup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (groupId: number) => {
      const response = await apiClient.delete<DeleteGroupResponse>(`/v2/groups/${groupId}`)
      return response
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: GROUPS_QUERY_KEY })
      toast.success(data.message || 'Group deleted successfully')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to delete group')
    },
  })
}

/**
 * Add a member to a group (admin only)
 */
export function useAddGroupMember() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ groupId, request }: { groupId: number; request: AddMemberRequest }) => {
      const response = await apiClient.post<AddMemberResponse>(`/v2/groups/${groupId}/members`, request)
      return response
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: GROUPS_QUERY_KEY })
      toast.success(data.message || 'Member added successfully')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to add member')
    },
  })
}

/**
 * Remove a member from a group (admin only)
 */
export function useRemoveGroupMember() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ groupId, userId }: { groupId: number; userId: number }) => {
      const response = await apiClient.delete<RemoveMemberResponse>(`/v2/groups/${groupId}/members/${userId}`)
      return response
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: GROUPS_QUERY_KEY })
      toast.success(data.message || 'Member removed successfully')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to remove member')
    },
  })
}
