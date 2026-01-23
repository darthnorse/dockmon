/**
 * Edit User Modal
 * Form to edit an existing user's details and role
 *
 * Phase 3 of Multi-User Support (v2.3.0)
 */

import { useState, useEffect, type FormEvent } from 'react'
import { X, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useUser, useUpdateUser } from '@/hooks/useUsers'
import type { UpdateUserRequest, UserRole } from '@/types/users'
import { USER_ROLES, ROLE_LABELS, ROLE_DESCRIPTIONS } from '@/types/users'
import { toast } from 'sonner'

interface EditUserModalProps {
  isOpen: boolean
  onClose: () => void
  userId: number
}

export function EditUserModal({ isOpen, onClose, userId }: EditUserModalProps) {
  const { data: user, isLoading } = useUser(userId)
  const updateUser = useUpdateUser()

  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<UserRole>('user')

  // Initialize form when user data loads
  useEffect(() => {
    if (user) {
      setEmail(user.email || '')
      setDisplayName(user.display_name || '')
      setRole(user.role)
    }
  }, [user])

  if (!isOpen) return null

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    if (!user) return

    try {
      const request: UpdateUserRequest = {}

      // Only include fields that changed
      const newEmail = email.trim() || null
      const newDisplayName = displayName.trim() || null

      if (newEmail !== user.email) {
        request.email = newEmail
      }

      if (newDisplayName !== user.display_name) {
        request.display_name = newDisplayName
      }

      if (role !== user.role) {
        request.role = role
      }

      // Check if anything changed
      if (Object.keys(request).length === 0) {
        toast.info('No changes to save')
        onClose()
        return
      }

      await updateUser.mutateAsync({ userId, data: request })
      onClose()
    } catch {
      // Error handled by mutation
    }
  }

  const handleClose = () => {
    if (updateUser.isPending) return
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="mx-4 max-h-[90vh] w-full max-w-md overflow-y-auto rounded-lg border border-gray-800 bg-gray-900">
        {/* Header */}
        <div className="sticky top-0 flex items-center justify-between border-b border-gray-800 bg-gray-900 px-6 py-4">
          <h2 className="text-lg font-semibold text-white">Edit User</h2>
          <button
            onClick={handleClose}
            disabled={updateUser.isPending}
            className="text-gray-400 hover:text-gray-300"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
          </div>
        ) : !user ? (
          <div className="py-12 text-center text-gray-400">User not found</div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5 p-6">
            {/* Username (read-only) */}
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-300">Username</label>
              <Input
                type="text"
                value={user.username}
                disabled
                className="w-full bg-gray-800/50 text-gray-400"
              />
              <p className="mt-1 text-xs text-gray-500">Username cannot be changed</p>
            </div>

            {/* Display Name */}
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-300">Display Name</label>
              <Input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="e.g., John Doe"
                disabled={updateUser.isPending}
                className="w-full"
              />
              <p className="mt-1 text-xs text-gray-500">Optional friendly name shown in the UI</p>
            </div>

            {/* Email */}
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-300">Email</label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="e.g., john@example.com"
                disabled={updateUser.isPending}
                className="w-full"
              />
              <p className="mt-1 text-xs text-gray-500">
                Optional. Used for password reset and OIDC matching.
              </p>
            </div>

            {/* Role Selection */}
            <div>
              <label className="mb-3 block text-sm font-medium text-gray-300">Role</label>
              <div className="space-y-2">
                {USER_ROLES.map((r) => (
                  <label
                    key={r}
                    className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                      role === r
                        ? 'border-blue-500 bg-blue-900/30'
                        : 'border-gray-700 bg-gray-800/50 hover:border-gray-600'
                    }`}
                  >
                    <input
                      type="radio"
                      name="role"
                      value={r}
                      checked={role === r}
                      onChange={() => setRole(r)}
                      disabled={updateUser.isPending}
                      className="mt-0.5 h-4 w-4 border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500"
                    />
                    <div>
                      <div className="font-medium text-white">{ROLE_LABELS[r]}</div>
                      <div className="text-xs text-gray-400">{ROLE_DESCRIPTIONS[r]}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {/* Auth Provider Info */}
            {user.auth_provider === 'oidc' && (
              <div className="rounded-lg border border-cyan-900/30 bg-cyan-900/10 p-3">
                <p className="text-sm text-cyan-300">
                  This is an SSO user. Their role may be overridden by OIDC group mappings on next
                  login.
                </p>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2 pt-2">
              <Button type="submit" disabled={updateUser.isPending} className="flex-1">
                {updateUser.isPending ? 'Saving...' : 'Save Changes'}
              </Button>
              <Button
                type="button"
                onClick={handleClose}
                disabled={updateUser.isPending}
                variant="outline"
                className="flex-1"
              >
                Cancel
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
