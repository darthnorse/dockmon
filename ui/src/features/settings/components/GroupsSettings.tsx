/**
 * Groups Settings Component
 * Admin-only custom groups management interface
 *
 * Group-Based Permissions Refactor (v2.4.0)
 */

import { useState, useEffect } from 'react'
import {
  RefreshCw,
  Plus,
  Users,
  Trash2,
  Edit2,
  UserPlus,
  UserMinus,
  ChevronDown,
  ChevronRight,
  Lock,
  Shield,
} from 'lucide-react'
import {
  useGroups,
  useGroup,
  useCreateGroup,
  useUpdateGroup,
  useDeleteGroup,
  useAddGroupMember,
  useRemoveGroupMember,
} from '@/hooks/useGroups'
import { useUsers } from '@/hooks/useUsers'
import type { Group, GroupMember, CreateGroupRequest, UpdateGroupRequest } from '@/types/groups'
import type { User } from '@/types/users'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { formatDateTime } from '@/lib/utils/timeFormat'

export function GroupsSettings() {
  const { data: groupsData, isLoading, refetch } = useGroups()
  const { data: usersData } = useUsers(false) // Active users only

  const createGroup = useCreateGroup()
  const updateGroup = useUpdateGroup()
  const deleteGroup = useDeleteGroup()
  const addMember = useAddGroupMember()
  const removeMember = useRemoveGroupMember()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingGroup, setEditingGroup] = useState<Group | null>(null)
  const [deletingGroup, setDeletingGroup] = useState<Group | null>(null)
  const [expandedGroupId, setExpandedGroupId] = useState<number | null>(null)
  const [addingMemberGroupId, setAddingMemberGroupId] = useState<number | null>(null)
  const [removingMember, setRemovingMember] = useState<{
    groupId: number
    userId: number
    username: string
  } | null>(null)

  // Get expanded group data
  const { data: expandedGroupData } = useGroup(expandedGroupId)

  const groups = groupsData?.groups || []
  const users = usersData?.users || []

  // Toggle group expansion
  const toggleGroup = (groupId: number) => {
    setExpandedGroupId(expandedGroupId === groupId ? null : groupId)
  }

  // Handle create group
  const handleCreate = async (request: CreateGroupRequest) => {
    await createGroup.mutateAsync(request)
    setShowCreateModal(false)
  }

  // Handle update group
  const handleUpdate = async (request: UpdateGroupRequest) => {
    if (!editingGroup) return
    await updateGroup.mutateAsync({ groupId: editingGroup.id, request })
    setEditingGroup(null)
  }

  // Handle delete group
  const handleDeleteConfirm = async () => {
    if (!deletingGroup || deletingGroup.is_system) return
    await deleteGroup.mutateAsync(deletingGroup.id)
    setDeletingGroup(null)
    if (expandedGroupId === deletingGroup.id) {
      setExpandedGroupId(null)
    }
  }

  // Handle add member
  const handleAddMember = async (userId: number) => {
    if (!addingMemberGroupId) return
    await addMember.mutateAsync({
      groupId: addingMemberGroupId,
      request: { user_id: userId },
    })
    setAddingMemberGroupId(null)
  }

  // Handle remove member
  const handleRemoveMemberConfirm = async () => {
    if (!removingMember) return
    await removeMember.mutateAsync({
      groupId: removingMember.groupId,
      userId: removingMember.userId,
    })
    setRemovingMember(null)
  }

  // Get users not in the expanded group (for add member)
  const getAvailableUsers = () => {
    if (!expandedGroupData || !addingMemberGroupId) return []
    const memberIds = new Set(expandedGroupData.members.map((m) => m.user_id))
    return users.filter((u) => !memberIds.has(u.id) && !u.is_deleted)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">Groups</h2>
          <p className="mt-1 text-sm text-gray-400">
            Organize users into groups with customizable permissions
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button size="sm" onClick={() => setShowCreateModal(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Group
          </Button>
        </div>
      </div>

      {/* Groups list */}
      {isLoading ? (
        <div className="flex h-32 items-center justify-center">
          <RefreshCw className="h-6 w-6 animate-spin text-gray-400" />
        </div>
      ) : groups.length === 0 ? (
        <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-8 text-center">
          <Users className="mx-auto h-12 w-12 text-gray-500" />
          <h3 className="mt-4 text-sm font-medium text-gray-300">No groups yet</h3>
          <p className="mt-1 text-sm text-gray-500">
            Create a group to organize users together.
          </p>
          <Button size="sm" className="mt-4" onClick={() => setShowCreateModal(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Group
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          {groups.map((group) => (
            <GroupRow
              key={group.id}
              group={group}
              expanded={expandedGroupId === group.id}
              expandedData={expandedGroupId === group.id && expandedGroupData ? expandedGroupData : null}
              onToggle={() => toggleGroup(group.id)}
              onEdit={() => setEditingGroup(group)}
              onDelete={() => setDeletingGroup(group)}
              onAddMember={() => setAddingMemberGroupId(group.id)}
              onRemoveMember={(userId, username) =>
                setRemovingMember({ groupId: group.id, userId, username })
              }
            />
          ))}
        </div>
      )}

      {/* Create Group Modal */}
      <CreateGroupModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSubmit={handleCreate}
        isSubmitting={createGroup.isPending}
      />

      {/* Edit Group Modal */}
      <EditGroupModal
        group={editingGroup}
        isOpen={editingGroup !== null}
        onClose={() => setEditingGroup(null)}
        onSubmit={handleUpdate}
        isSubmitting={updateGroup.isPending}
      />

      {/* Delete confirmation dialog */}
      <Dialog open={deletingGroup !== null} onOpenChange={() => setDeletingGroup(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Group</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete the group "{deletingGroup?.name}"?
              {deletingGroup && deletingGroup.member_count > 0 && (
                <span className="mt-2 block text-yellow-400">
                  This group has {deletingGroup.member_count} member(s) who will be removed.
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingGroup(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteGroup.isPending}
            >
              {deleteGroup.isPending && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Member Modal */}
      <AddMemberModal
        isOpen={addingMemberGroupId !== null}
        onClose={() => setAddingMemberGroupId(null)}
        onSubmit={handleAddMember}
        availableUsers={getAvailableUsers()}
        isSubmitting={addMember.isPending}
      />

      {/* Remove Member confirmation dialog */}
      <Dialog open={removingMember !== null} onOpenChange={() => setRemovingMember(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove Member</DialogTitle>
            <DialogDescription>
              Are you sure you want to remove user "{removingMember?.username}" from this group?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemovingMember(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleRemoveMemberConfirm}
              disabled={removeMember.isPending}
            >
              {removeMember.isPending && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// Group row component
interface GroupRowProps {
  group: Group
  expanded: boolean
  expandedData: { members: GroupMember[] } | null
  onToggle: () => void
  onEdit: () => void
  onDelete: () => void
  onAddMember: () => void
  onRemoveMember: (userId: number, username: string) => void
}

function GroupRow({
  group,
  expanded,
  expandedData,
  onToggle,
  onEdit,
  onDelete,
  onAddMember,
  onRemoveMember,
}: GroupRowProps) {
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/50">
      {/* Group header */}
      <div
        className="flex cursor-pointer items-center justify-between p-4 hover:bg-gray-800"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          {expanded ? (
            <ChevronDown className="h-5 w-5 text-gray-400" />
          ) : (
            <ChevronRight className="h-5 w-5 text-gray-400" />
          )}
          <Users className="h-5 w-5 text-blue-400" />
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-medium text-white">{group.name}</h3>
              {group.is_system && (
                <span className="flex items-center gap-1 rounded bg-purple-900/50 px-1.5 py-0.5 text-xs text-purple-300">
                  <Shield className="h-3 w-3" />
                  System
                </span>
              )}
            </div>
            {group.description && (
              <p className="text-sm text-gray-400">{group.description}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <span className="rounded-full bg-gray-700 px-2 py-0.5 text-xs text-gray-300">
            {group.member_count} member{group.member_count !== 1 ? 's' : ''}
          </span>
          <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
            <Button variant="ghost" size="sm" onClick={onEdit}>
              <Edit2 className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onDelete}
              className={group.is_system ? 'text-gray-600 cursor-not-allowed' : 'text-red-400'}
              disabled={group.is_system}
              title={group.is_system ? 'System groups cannot be deleted' : 'Delete group'}
            >
              {group.is_system ? <Lock className="h-4 w-4" /> : <Trash2 className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </div>

      {/* Expanded content - members list */}
      {expanded && (
        <div className="border-t border-gray-700 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-medium text-gray-300">Members</h4>
            <Button size="sm" variant="outline" onClick={onAddMember}>
              <UserPlus className="mr-2 h-4 w-4" />
              Add Member
            </Button>
          </div>

          {!expandedData ? (
            <div className="flex h-16 items-center justify-center">
              <RefreshCw className="h-4 w-4 animate-spin text-gray-400" />
            </div>
          ) : expandedData.members.length === 0 ? (
            <p className="text-sm text-gray-500">No members in this group yet.</p>
          ) : (
            <div className="space-y-2">
              {expandedData.members.map((member) => (
                <div
                  key={member.user_id}
                  className="flex items-center justify-between rounded-md bg-gray-900/50 p-2"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-700 text-sm font-medium text-gray-300">
                      {member.username.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <span className="text-sm font-medium text-white">{member.username}</span>
                      {member.display_name && (
                        <span className="ml-2 text-sm text-gray-400">({member.display_name})</span>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onRemoveMember(member.user_id, member.username)}
                    className="text-red-400"
                  >
                    <UserMinus className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          {group.created_by && (
            <p className="mt-4 text-xs text-gray-500">
              Created by {group.created_by} on {formatDateTime(group.created_at)}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// Create Group Modal
interface CreateGroupModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (request: CreateGroupRequest) => void
  isSubmitting: boolean
}

function CreateGroupModal({ isOpen, onClose, onSubmit, isSubmitting }: CreateGroupModalProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({ name, description: description || undefined })
    setName('')
    setDescription('')
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Create Group</DialogTitle>
            <DialogDescription>Create a new group to organize users.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="name">Group Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., DevOps Team"
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="description">Description (optional)</Label>
              <Textarea
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What is this group for?"
                rows={2}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || !name.trim()}>
              {isSubmitting && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Create Group
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// Edit Group Modal
interface EditGroupModalProps {
  group: Group | null
  isOpen: boolean
  onClose: () => void
  onSubmit: (request: UpdateGroupRequest) => void
  isSubmitting: boolean
}

function EditGroupModal({ group, isOpen, onClose, onSubmit, isSubmitting }: EditGroupModalProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  // Initialize form when group changes (proper useEffect pattern)
  useEffect(() => {
    if (group) {
      setName(group.name)
      setDescription(group.description || '')
    }
  }, [group])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({ name, description: description || undefined })
  }

  const handleClose = () => {
    setName('')
    setDescription('')
    onClose()
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Edit Group</DialogTitle>
            <DialogDescription>Update group information.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="edit-name">Group Name</Label>
              <Input
                id="edit-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., DevOps Team"
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="edit-description">Description (optional)</Label>
              <Textarea
                id="edit-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What is this group for?"
                rows={2}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || !name.trim()}>
              {isSubmitting && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Save Changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// Add Member Modal
interface AddMemberModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (userId: number) => void
  availableUsers: User[]
  isSubmitting: boolean
}

function AddMemberModal({
  isOpen,
  onClose,
  onSubmit,
  availableUsers,
  isSubmitting,
}: AddMemberModalProps) {
  const [selectedUserId, setSelectedUserId] = useState<string>('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (selectedUserId) {
      onSubmit(parseInt(selectedUserId, 10))
      setSelectedUserId('')
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Add Member</DialogTitle>
            <DialogDescription>Select a user to add to this group.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            {availableUsers.length === 0 ? (
              <p className="text-sm text-gray-400">
                All active users are already members of this group.
              </p>
            ) : (
              <div className="grid gap-2">
                <Label>User</Label>
                <Select value={selectedUserId} onValueChange={setSelectedUserId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a user" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableUsers.map((user) => (
                      <SelectItem key={user.id} value={user.id.toString()}>
                        {user.username}
                        {user.display_name && ` (${user.display_name})`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting || !selectedUserId || availableUsers.length === 0}
            >
              {isSubmitting && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Add Member
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
