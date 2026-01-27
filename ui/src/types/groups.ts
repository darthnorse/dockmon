/**
 * Custom Groups Types
 * Group-Based Permissions Refactor (v2.4.0)
 */

// Group member
export interface GroupMember {
  user_id: number
  username: string
  display_name: string | null
  email: string | null
  role: string  // User's legacy role (for display)
  added_at: string
  added_by: string | null  // Username of who added this member
}

// Group summary (for list view)
export interface Group {
  id: number
  name: string
  description: string | null
  is_system: boolean  // System groups cannot be deleted
  member_count: number
  created_at: string
  created_by: string | null
  updated_at: string
}

// Group permission with metadata (from backend)
export interface GroupPermissionResponse {
  capability: string
  allowed: boolean
  category: string
  display_name: string
  description: string
}

// Group permissions list response (GET /v2/groups/{id}/permissions)
export interface GroupPermissionsResponse {
  group_id: number
  group_name: string
  permissions: GroupPermissionResponse[]
}

// Update group permissions response
export interface UpdatePermissionsResponse {
  updated: number
  message: string
}

// Update group permissions request
export interface UpdateGroupPermissionsRequest {
  permissions: Array<{
    capability: string
    allowed: boolean
  }>
}

// User's group membership (for /me endpoint)
export interface UserGroupInfo {
  id: number
  name: string
}

// Group with members (for detail view)
export interface GroupDetail {
  id: number
  name: string
  description: string | null
  is_system: boolean  // System groups cannot be deleted
  members: GroupMember[]
  created_at: string
  created_by: string | null
  updated_at: string
}

// List response
export interface GroupListResponse {
  groups: Group[]
  total: number
}

// Create request
export interface CreateGroupRequest {
  name: string
  description?: string | undefined
}

// Update request
export interface UpdateGroupRequest {
  name?: string | undefined
  description?: string | undefined
}

// Add member request
export interface AddMemberRequest {
  user_id: number
}

// Response types
export interface AddMemberResponse {
  success: boolean
  message: string
}

export interface RemoveMemberResponse {
  success: boolean
  message: string
}

export interface DeleteGroupResponse {
  success: boolean
  message: string
}

// All group permissions response (bulk endpoint)
export interface AllGroupPermissionsResponse {
  permissions: Record<number, Record<string, boolean>>
}

// Copy permissions response (may include warning)
export interface CopyPermissionsResponse {
  copied: number
  message: string
  warning?: string
}
