/**
 * Users Settings Component
 * Admin-only user management interface
 *
 * Group-Based Permissions Refactor (v2.4.0)
 */

import { useState } from 'react'
import {
  Trash2,
  Edit2,
  Plus,
  User as UserIcon,
  Users,
  Key,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react'
import { useAuth } from '@/features/auth/AuthContext'
import { useUsers, useDeleteUser, useApproveUser } from '@/hooks/useUsers'
import { CreateUserModal } from './Users/CreateUserModal'
import { EditUserModal } from './Users/EditUserModal'
import { ResetPasswordModal } from './Users/ResetPasswordModal'
import type { User } from '@/types/users'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatDateTime } from '@/lib/utils/timeFormat'

export function UsersSettings() {
  const { user: currentUser } = useAuth()
  const { data, isLoading, refetch } = useUsers()
  const deleteUser = useDeleteUser()
  const { mutate: approveUser, isPending: isApproving } = useApproveUser()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingUserId, setEditingUserId] = useState<number | null>(null)
  const [resetPasswordUserId, setResetPasswordUserId] = useState<number | null>(null)
  const [deletingUser, setDeletingUser] = useState<User | null>(null)

  const handleDeleteConfirm = async () => {
    if (!deletingUser) return
    try {
      await deleteUser.mutateAsync(deletingUser.id)
      setDeletingUser(null)
    } catch {
      // Error handled by mutation
    }
  }

  const users = data?.users || []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">User Management</h2>
          <p className="mt-1 text-sm text-gray-400">
            Create and manage user accounts with group-based access control
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button onClick={() => setShowCreateModal(true)} variant="default" size="sm">
            <Plus className="mr-2 h-4 w-4" />
            Create User
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-gray-400">Loading users...</div>
      ) : users.length === 0 ? (
        <div className="rounded-lg border border-gray-800 bg-gray-900/30 p-8 text-center">
          <UserIcon className="mx-auto mb-3 h-12 w-12 text-gray-600" />
          <h3 className="font-medium text-gray-400">No users found</h3>
          <p className="mt-1 text-sm text-gray-500">Create your first user to get started</p>
        </div>
      ) : (
        <div className="space-y-3">
          {users.map((user) => {
            const isOidc = user.auth_provider === 'oidc'

            return (
              <div
                key={user.id}
                className="rounded-lg border border-gray-800 bg-gray-900/50 p-4 transition-colors hover:bg-gray-900/70"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-medium text-white">
                        {user.display_name || user.username}
                      </h3>
                      {user.display_name && (
                        <span className="text-sm text-gray-500">@{user.username}</span>
                      )}
                      {user.groups?.map((group) => (
                        <span
                          key={group.id}
                          className="rounded bg-blue-900/50 px-2 py-0.5 text-xs text-blue-300"
                        >
                          <Users className="mr-1 inline-block h-3 w-3" />
                          {group.name}
                        </span>
                      ))}
                      {(!user.groups || user.groups.length === 0) && (
                        <span className="rounded bg-gray-700/50 px-2 py-0.5 text-xs text-gray-400">
                          No groups
                        </span>
                      )}
                      {isOidc && (
                        <span className="rounded bg-cyan-900/50 px-2 py-0.5 text-xs text-cyan-300">
                          SSO
                        </span>
                      )}
                      {user.must_change_password && (
                        <span className="rounded bg-yellow-900/50 px-2 py-0.5 text-xs text-yellow-300">
                          Password Reset Required
                        </span>
                      )}
                      {!user.approved && (
                        <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs font-medium text-amber-400">
                          Pending
                        </span>
                      )}
                    </div>

                    {user.email && (
                      <p className="mt-1 text-sm text-gray-400">{user.email}</p>
                    )}

                    <div className="mt-3 flex flex-wrap gap-4 text-xs text-gray-500">
                      <div>
                        <span className="text-gray-400">Created:</span>{' '}
                        {formatDateTime(user.created_at)}
                      </div>
                      {user.last_login && (
                        <div>
                          <span className="text-gray-400">Last login:</span>{' '}
                          {formatDateTime(user.last_login)}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="ml-4 flex gap-2">
                    {!user.approved && (
                      <button
                        onClick={() => approveUser(user.id)}
                        disabled={isApproving}
                        className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500 disabled:opacity-50"
                      >
                        Approve
                      </button>
                    )}
                    <button
                      onClick={() => setEditingUserId(user.id)}
                      className="rounded p-2 text-gray-400 transition-colors hover:bg-gray-700 hover:text-gray-300"
                      title="Edit user"
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                    {!isOidc && (
                      <button
                        onClick={() => setResetPasswordUserId(user.id)}
                        className="rounded p-2 text-yellow-400 transition-colors hover:bg-yellow-900/30 hover:text-yellow-300"
                        title="Reset password"
                      >
                        <Key className="h-4 w-4" />
                      </button>
                    )}
                    <button
                      onClick={() => setDeletingUser(user)}
                      disabled={deleteUser.isPending || user.id === currentUser?.id}
                      className="rounded p-2 text-red-400 transition-colors hover:bg-red-900/30 hover:text-red-300 disabled:opacity-50"
                      title={user.id === currentUser?.id ? 'You cannot delete your own account' : 'Delete user'}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Create User Modal */}
      <CreateUserModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
      />

      {/* Edit User Modal */}
      <EditUserModal
        isOpen={editingUserId !== null}
        onClose={() => setEditingUserId(null)}
        userId={editingUserId ?? 0}
      />

      {/* Reset Password Modal */}
      <ResetPasswordModal
        isOpen={resetPasswordUserId !== null}
        onClose={() => setResetPasswordUserId(null)}
        userId={resetPasswordUserId ?? 0}
      />

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deletingUser} onOpenChange={(open) => !open && setDeletingUser(null)}>
        <DialogContent>
          <DialogHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-900/20">
                <AlertTriangle className="h-5 w-5 text-red-400" />
              </div>
              <div>
                <DialogTitle>Delete User</DialogTitle>
                <DialogDescription className="mt-1">
                  This action cannot be undone. The user will be permanently deleted.
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          {deletingUser && (
            <div className="my-4">
              <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-3">
                <p className="font-medium text-white">
                  {deletingUser.display_name || deletingUser.username}
                </p>
                {deletingUser.email && (
                  <p className="text-sm text-gray-400">{deletingUser.email}</p>
                )}
              </div>
              <p className="mt-3 text-sm text-gray-400">
                The user account and all associated data will be permanently removed.
                Audit log entries will be preserved.
              </p>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingUser(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteUser.isPending}
            >
              {deleteUser.isPending ? 'Deleting...' : 'Delete User'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
