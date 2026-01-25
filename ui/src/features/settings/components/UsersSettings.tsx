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
  RotateCcw,
  Key,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react'
import { useUsers, useDeleteUser, useReactivateUser } from '@/hooks/useUsers'
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
  const [showDeleted, setShowDeleted] = useState(false)
  const { data, isLoading, refetch } = useUsers(showDeleted)
  const deleteUser = useDeleteUser()
  const reactivateUser = useReactivateUser()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingUserId, setEditingUserId] = useState<number | null>(null)
  const [resetPasswordUserId, setResetPasswordUserId] = useState<number | null>(null)
  const [deletingUser, setDeletingUser] = useState<User | null>(null)
  const [reactivatingUser, setReactivatingUser] = useState<User | null>(null)

  const handleDeleteConfirm = async () => {
    if (!deletingUser) return
    try {
      await deleteUser.mutateAsync(deletingUser.id)
      setDeletingUser(null)
    } catch {
      // Error handled by mutation
    }
  }

  const handleReactivateConfirm = async () => {
    if (!reactivatingUser) return
    try {
      await reactivateUser.mutateAsync(reactivatingUser.id)
      setReactivatingUser(null)
    } catch {
      // Error handled by mutation
    }
  }

  // Filter and count
  const users = data?.users || []
  const deletedCount = users.filter((u) => u.is_deleted).length
  const activeUsers = showDeleted ? users : users.filter((u) => !u.is_deleted)

  return (
    <div className="space-y-6">
      {/* Header */}
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

      {/* Show Deleted Toggle */}
      {deletedCount > 0 && (
        <div className="flex items-center gap-2">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-400 hover:text-gray-300">
            <input
              type="checkbox"
              checked={showDeleted}
              onChange={(e) => setShowDeleted(e.target.checked)}
              className="h-4 w-4 rounded border-gray-700 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-600 focus:ring-offset-0"
            />
            Show deactivated users ({deletedCount})
          </label>
        </div>
      )}

      {/* Users List */}
      {isLoading ? (
        <div className="py-8 text-center text-gray-400">Loading users...</div>
      ) : activeUsers.length === 0 ? (
        <div className="rounded-lg border border-gray-800 bg-gray-900/30 p-8 text-center">
          <UserIcon className="mx-auto mb-3 h-12 w-12 text-gray-600" />
          <h3 className="font-medium text-gray-400">No users found</h3>
          <p className="mt-1 text-sm text-gray-500">Create your first user to get started</p>
        </div>
      ) : (
        <div className="space-y-3">
          {activeUsers.map((user) => {
            const isOidc = user.auth_provider === 'oidc'

            return (
              <div
                key={user.id}
                className={`rounded-lg border p-4 transition-colors hover:bg-gray-900/70 ${
                  user.is_deleted
                    ? 'border-red-900/30 bg-red-900/10'
                    : 'border-gray-800 bg-gray-900/50'
                }`}
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
                      {/* Group badges */}
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
                      {user.is_deleted && (
                        <span className="rounded bg-red-900/50 px-2 py-0.5 text-xs text-red-300">
                          Deactivated
                        </span>
                      )}
                      {user.must_change_password && !user.is_deleted && (
                        <span className="rounded bg-yellow-900/50 px-2 py-0.5 text-xs text-yellow-300">
                          Password Reset Required
                        </span>
                      )}
                    </div>

                    {user.email && (
                      <p className="mt-1 text-sm text-gray-400">{user.email}</p>
                    )}

                    {/* User Details */}
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
                      {user.is_deleted && user.deleted_at && (
                        <div>
                          <span className="text-gray-400">Deactivated:</span>{' '}
                          {formatDateTime(user.deleted_at)}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="ml-4 flex gap-2">
                    {user.is_deleted ? (
                      <button
                        onClick={() => setReactivatingUser(user)}
                        disabled={reactivateUser.isPending}
                        className="rounded p-2 text-green-400 transition-colors hover:bg-green-900/30 hover:text-green-300 disabled:opacity-50"
                        title="Reactivate user"
                      >
                        <RotateCcw className="h-4 w-4" />
                      </button>
                    ) : (
                      <>
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
                          disabled={deleteUser.isPending}
                          className="rounded p-2 text-red-400 transition-colors hover:bg-red-900/30 hover:text-red-300 disabled:opacity-50"
                          title="Deactivate user"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </>
                    )}
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
                <DialogTitle>Deactivate User</DialogTitle>
                <DialogDescription className="mt-1">
                  This user will no longer be able to log in.
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
                The user account will be deactivated but preserved for audit purposes. You can
                reactivate it later if needed.
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
              {deleteUser.isPending ? 'Deactivating...' : 'Deactivate User'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reactivate Confirmation Dialog */}
      <Dialog
        open={!!reactivatingUser}
        onOpenChange={(open) => !open && setReactivatingUser(null)}
      >
        <DialogContent>
          <DialogHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-green-900/20">
                <RotateCcw className="h-5 w-5 text-green-400" />
              </div>
              <div>
                <DialogTitle>Reactivate User</DialogTitle>
                <DialogDescription className="mt-1">
                  This user will be able to log in again.
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          {reactivatingUser && (
            <div className="my-4">
              <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-3">
                <p className="font-medium text-white">
                  {reactivatingUser.display_name || reactivatingUser.username}
                </p>
                {reactivatingUser.email && (
                  <p className="text-sm text-gray-400">{reactivatingUser.email}</p>
                )}
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setReactivatingUser(null)}>
              Cancel
            </Button>
            <Button
              variant="default"
              onClick={handleReactivateConfirm}
              disabled={reactivateUser.isPending}
            >
              {reactivateUser.isPending ? 'Reactivating...' : 'Reactivate User'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
