/**
 * Create User Modal
 * Form to create a new user with role selection
 *
 * Phase 3 of Multi-User Support (v2.3.0)
 */

import { useState, type FormEvent } from 'react'
import { X, Eye, EyeOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCreateUser } from '@/hooks/useUsers'
import type { CreateUserRequest, UserRole } from '@/types/users'
import { USER_ROLES, ROLE_LABELS, ROLE_DESCRIPTIONS } from '@/types/users'
import { toast } from 'sonner'

interface CreateUserModalProps {
  isOpen: boolean
  onClose: () => void
}

export function CreateUserModal({ isOpen, onClose }: CreateUserModalProps) {
  const createUser = useCreateUser()

  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [role, setRole] = useState<UserRole>('user')
  const [mustChangePassword, setMustChangePassword] = useState(true)
  const [showPassword, setShowPassword] = useState(false)

  if (!isOpen) return null

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    // Validation
    if (!username.trim()) {
      toast.error('Username is required')
      return
    }

    if (!/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(username)) {
      toast.error('Username must start with a letter and contain only letters, numbers, underscores, and hyphens')
      return
    }

    if (!password) {
      toast.error('Password is required')
      return
    }

    if (password.length < 8) {
      toast.error('Password must be at least 8 characters')
      return
    }

    if (password !== confirmPassword) {
      toast.error('Passwords do not match')
      return
    }

    try {
      const request: CreateUserRequest = {
        username: username.trim(),
        password,
        role,
        must_change_password: mustChangePassword,
      }

      if (email.trim()) {
        request.email = email.trim()
      }

      if (displayName.trim()) {
        request.display_name = displayName.trim()
      }

      await createUser.mutateAsync(request)

      // Reset form
      resetForm()
      onClose()
    } catch {
      // Error handled by mutation
    }
  }

  const resetForm = () => {
    setUsername('')
    setEmail('')
    setDisplayName('')
    setPassword('')
    setConfirmPassword('')
    setRole('user')
    setMustChangePassword(true)
    setShowPassword(false)
  }

  const handleClose = () => {
    if (createUser.isPending) return
    resetForm()
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="mx-4 max-h-[90vh] w-full max-w-md overflow-y-auto rounded-lg border border-gray-800 bg-gray-900">
        {/* Header */}
        <div className="sticky top-0 flex items-center justify-between border-b border-gray-800 bg-gray-900 px-6 py-4">
          <h2 className="text-lg font-semibold text-white">Create User</h2>
          <button
            onClick={handleClose}
            disabled={createUser.isPending}
            className="text-gray-400 hover:text-gray-300"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5 p-6">
          {/* Username */}
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-300">Username *</label>
            <Input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g., johndoe"
              disabled={createUser.isPending}
              className="w-full"
            />
            <p className="mt-1 text-xs text-gray-500">
              Must start with a letter. Letters, numbers, underscores, hyphens only.
            </p>
          </div>

          {/* Display Name */}
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-300">Display Name</label>
            <Input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="e.g., John Doe"
              disabled={createUser.isPending}
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
              disabled={createUser.isPending}
              className="w-full"
            />
            <p className="mt-1 text-xs text-gray-500">
              Optional. Used for password reset and OIDC matching.
            </p>
          </div>

          {/* Password */}
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-300">Password *</label>
            <div className="relative">
              <Input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Minimum 8 characters"
                disabled={createUser.isPending}
                className="w-full pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-300"
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {/* Confirm Password */}
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-300">Confirm Password *</label>
            <Input
              type={showPassword ? 'text' : 'password'}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter password"
              disabled={createUser.isPending}
              className="w-full"
            />
          </div>

          {/* Role Selection */}
          <div>
            <label className="mb-3 block text-sm font-medium text-gray-300">Role *</label>
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
                    disabled={createUser.isPending}
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

          {/* Must Change Password */}
          <div>
            <label className="flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={mustChangePassword}
                onChange={(e) => setMustChangePassword(e.target.checked)}
                disabled={createUser.isPending}
                className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500"
              />
              <div>
                <span className="text-sm font-medium text-gray-300">
                  Require password change on first login
                </span>
                <p className="text-xs text-gray-500">Recommended for security</p>
              </div>
            </label>
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            <Button type="submit" disabled={createUser.isPending} className="flex-1">
              {createUser.isPending ? 'Creating...' : 'Create User'}
            </Button>
            <Button
              type="button"
              onClick={handleClose}
              disabled={createUser.isPending}
              variant="outline"
              className="flex-1"
            >
              Cancel
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
