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
  added_at: string
  added_by: string | null
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

// Group permission (capability assigned to a group)
export interface GroupPermission {
  capability: string
  allowed: boolean
}

// Group permissions response
export interface GroupPermissionsResponse {
  group_id: number
  group_name: string
  permissions: Record<string, boolean>  // capability -> allowed
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
