/**
 * Custom Groups Types
 * Phase 5 of Multi-User Support (v2.3.0)
 */

// Group member
export interface GroupMember {
  user_id: number
  username: string
  display_name: string | null
  email: string | null
  role: string
  added_at: string
  added_by: string | null
}

// Group summary (for list view)
export interface Group {
  id: number
  name: string
  description: string | null
  member_count: number
  created_at: string
  created_by: string | null
  updated_at: string
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
