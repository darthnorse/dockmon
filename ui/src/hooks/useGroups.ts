/**
 * useGroups Hook
 * Manages Custom Groups CRUD operations with React Query
 *
 * Group-Based Permissions Refactor (v2.4.0)
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
  GroupPermissionsResponse,
  UpdateGroupPermissionsRequest,
} from '@/types/groups'
import { toast } from 'sonner'

const GROUPS_QUERY_KEY = ['groups']
const PERMISSIONS_QUERY_KEY = ['group-permissions']

/**
 * Fetch all groups (admin only)
 */
export function useGroups() {
  return useQuery({
    queryKey: GROUPS_QUERY_KEY,
    queryFn: () => apiClient.get<GroupListResponse>('/v2/groups'),
    staleTime: 30 * 1000, // 30 seconds
  })
}

/**
 * Get a single group with members (admin only)
 */
export function useGroup(groupId: number | null) {
  return useQuery({
    queryKey: [...GROUPS_QUERY_KEY, groupId],
    queryFn: () => apiClient.get<GroupDetail>(`/v2/groups/${groupId}`),
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
    queryFn: () => apiClient.get<GroupMember[]>(`/v2/groups/${groupId}/members`),
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
    mutationFn: (request: CreateGroupRequest) => apiClient.post<Group>('/v2/groups', request),
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
    mutationFn: ({ groupId, request }: { groupId: number; request: UpdateGroupRequest }) =>
      apiClient.put<Group>(`/v2/groups/${groupId}`, request),
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
    mutationFn: (groupId: number) => apiClient.delete<DeleteGroupResponse>(`/v2/groups/${groupId}`),
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
    mutationFn: ({ groupId, request }: { groupId: number; request: AddMemberRequest }) =>
      apiClient.post<AddMemberResponse>(`/v2/groups/${groupId}/members`, request),
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
    mutationFn: ({ groupId, userId }: { groupId: number; userId: number }) =>
      apiClient.delete<RemoveMemberResponse>(`/v2/groups/${groupId}/members/${userId}`),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: GROUPS_QUERY_KEY })
      toast.success(data.message || 'Member removed successfully')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to remove member')
    },
  })
}

// ==================== Group Permissions ====================

/**
 * Fetch permissions for a specific group
 */
export function useGroupPermissions(groupId: number | null) {
  return useQuery({
    queryKey: [...PERMISSIONS_QUERY_KEY, groupId],
    queryFn: () => apiClient.get<GroupPermissionsResponse>(`/v2/groups/${groupId}/permissions`),
    enabled: groupId !== null,
    staleTime: 30 * 1000,
  })
}

/**
 * Backend permission response format (array of objects with metadata)
 */
interface BackendPermissionItem {
  capability: string
  allowed: boolean
  category: string
  display_name: string
  description: string
}

interface BackendPermissionsResponse {
  group_id: number
  group_name: string
  permissions: BackendPermissionItem[]
}

/**
 * Fetch permissions for all groups (for permission matrix view)
 */
export function useAllGroupPermissions() {
  return useQuery({
    queryKey: [...PERMISSIONS_QUERY_KEY, 'all'],
    queryFn: async () => {
      // Get all groups first
      const groupsResponse = await apiClient.get<GroupListResponse>('/v2/groups')
      const groups = groupsResponse.groups || []

      // Fetch permissions for each group in parallel
      const permissionPromises = groups.map((group) =>
        apiClient
          .get<BackendPermissionsResponse>(`/v2/groups/${group.id}/permissions`)
          .then((res) => {
            // Transform backend list format to frontend dictionary format
            const permsDict: Record<string, boolean> = {}
            for (const perm of res.permissions) {
              permsDict[perm.capability] = perm.allowed
            }
            return { groupId: group.id, permissions: permsDict }
          })
      )
      const results = await Promise.all(permissionPromises)

      const permissionsMap: Record<number, Record<string, boolean>> = {}
      results.forEach((r) => {
        permissionsMap[r.groupId] = r.permissions
      })

      return { groups, permissions: permissionsMap }
    },
    staleTime: 30 * 1000,
  })
}

/**
 * Update permissions for a group
 */
export function useUpdateGroupPermissions() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ groupId, request }: { groupId: number; request: UpdateGroupPermissionsRequest }) =>
      apiClient.put<{ updated: number; message: string }>(`/v2/groups/${groupId}/permissions`, request),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: PERMISSIONS_QUERY_KEY })
      toast.success(data.message || 'Permissions updated successfully')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to update permissions')
    },
  })
}

/**
 * Copy permissions from one group to another
 */
export function useCopyGroupPermissions() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ targetGroupId, sourceGroupId }: { targetGroupId: number; sourceGroupId: number }) =>
      apiClient.post<{ message: string }>(`/v2/groups/${targetGroupId}/permissions/copy-from/${sourceGroupId}`, {}),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: PERMISSIONS_QUERY_KEY })
      toast.success(data.message || 'Permissions copied successfully')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to copy permissions')
    },
  })
}
