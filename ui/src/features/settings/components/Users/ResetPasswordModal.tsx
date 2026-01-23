/**
 * Reset Password Modal
 * Admin-initiated password reset for users
 *
 * Phase 3 of Multi-User Support (v2.3.0)
 */

import { useState, type FormEvent } from 'react'
import { X, Eye, EyeOff, Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useUser, useResetUserPassword } from '@/hooks/useUsers'
import type { ResetPasswordRequest } from '@/types/users'
import { toast } from 'sonner'

interface ResetPasswordModalProps {
  isOpen: boolean
  onClose: () => void
  userId: number
}

export function ResetPasswordModal({ isOpen, onClose, userId }: ResetPasswordModalProps) {
  const { data: user } = useUser(userId)
  const resetPassword = useResetUserPassword()

  const [mode, setMode] = useState<'generate' | 'custom'>('generate')
  const [customPassword, setCustomPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [generatedPassword, setGeneratedPassword] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  if (!isOpen) return null

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    if (mode === 'custom') {
      if (!customPassword) {
        toast.error('Password is required')
        return
      }
      if (customPassword.length < 8) {
        toast.error('Password must be at least 8 characters')
        return
      }
      if (customPassword !== confirmPassword) {
        toast.error('Passwords do not match')
        return
      }
    }

    try {
      const request: ResetPasswordRequest =
        mode === 'custom' ? { new_password: customPassword } : {}

      const response = await resetPassword.mutateAsync({ userId, data: request })

      if (response.temporary_password) {
        setGeneratedPassword(response.temporary_password)
      } else {
        onClose()
      }
    } catch {
      // Error handled by mutation
    }
  }

  const handleCopy = async () => {
    if (!generatedPassword) return
    try {
      await navigator.clipboard.writeText(generatedPassword)
      setCopied(true)
      toast.success('Password copied to clipboard')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error('Failed to copy to clipboard')
    }
  }

  const handleClose = () => {
    if (resetPassword.isPending) return
    setMode('generate')
    setCustomPassword('')
    setConfirmPassword('')
    setShowPassword(false)
    setGeneratedPassword(null)
    setCopied(false)
    onClose()
  }

  // Show generated password result
  if (generatedPassword) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="mx-4 w-full max-w-md rounded-lg border border-gray-800 bg-gray-900">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-gray-800 px-6 py-4">
            <h2 className="text-lg font-semibold text-white">Password Reset</h2>
            <button onClick={handleClose} className="text-gray-400 hover:text-gray-300">
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Content */}
          <div className="space-y-4 p-6">
            <div className="rounded-lg border border-green-900/30 bg-green-900/10 p-4">
              <p className="text-sm text-green-300">
                Password reset successfully for <strong>{user?.username}</strong>
              </p>
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-gray-300">
                Temporary Password
              </label>
              <div className="flex gap-2">
                <code className="flex-1 rounded border border-gray-700 bg-gray-800 px-3 py-2 font-mono text-white">
                  {generatedPassword}
                </code>
                <Button
                  type="button"
                  onClick={handleCopy}
                  variant="outline"
                  size="icon"
                  className="h-10 w-10"
                >
                  {copied ? (
                    <Check className="h-4 w-4 text-green-400" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>

            <div className="rounded bg-yellow-900/20 border border-yellow-900/30 p-3">
              <p className="text-xs text-yellow-300">
                <strong>Save this password now.</strong> It will not be shown again. The user will be
                required to change it on their next login.
              </p>
            </div>

            <Button type="button" onClick={handleClose} className="w-full">
              Done
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="mx-4 max-h-[90vh] w-full max-w-md overflow-y-auto rounded-lg border border-gray-800 bg-gray-900">
        {/* Header */}
        <div className="sticky top-0 flex items-center justify-between border-b border-gray-800 bg-gray-900 px-6 py-4">
          <h2 className="text-lg font-semibold text-white">Reset Password</h2>
          <button
            onClick={handleClose}
            disabled={resetPassword.isPending}
            className="text-gray-400 hover:text-gray-300"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5 p-6">
          {/* User Info */}
          {user && (
            <div className="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
              <p className="font-medium text-white">{user.display_name || user.username}</p>
              {user.email && <p className="text-sm text-gray-400">{user.email}</p>}
            </div>
          )}

          {/* Mode Selection */}
          <div>
            <label className="mb-3 block text-sm font-medium text-gray-300">
              Password Reset Method
            </label>
            <div className="space-y-2">
              <label
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                  mode === 'generate'
                    ? 'border-blue-500 bg-blue-900/30'
                    : 'border-gray-700 bg-gray-800/50 hover:border-gray-600'
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  value="generate"
                  checked={mode === 'generate'}
                  onChange={() => setMode('generate')}
                  disabled={resetPassword.isPending}
                  className="mt-0.5 h-4 w-4 border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500"
                />
                <div>
                  <div className="font-medium text-white">Generate Random Password</div>
                  <div className="text-xs text-gray-400">
                    A secure random password will be generated
                  </div>
                </div>
              </label>

              <label
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                  mode === 'custom'
                    ? 'border-blue-500 bg-blue-900/30'
                    : 'border-gray-700 bg-gray-800/50 hover:border-gray-600'
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  value="custom"
                  checked={mode === 'custom'}
                  onChange={() => setMode('custom')}
                  disabled={resetPassword.isPending}
                  className="mt-0.5 h-4 w-4 border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500"
                />
                <div>
                  <div className="font-medium text-white">Set Custom Password</div>
                  <div className="text-xs text-gray-400">Enter a specific password</div>
                </div>
              </label>
            </div>
          </div>

          {/* Custom Password Fields */}
          {mode === 'custom' && (
            <>
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-300">
                  New Password *
                </label>
                <div className="relative">
                  <Input
                    type={showPassword ? 'text' : 'password'}
                    value={customPassword}
                    onChange={(e) => setCustomPassword(e.target.value)}
                    placeholder="Minimum 8 characters"
                    disabled={resetPassword.isPending}
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

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-300">
                  Confirm Password *
                </label>
                <Input
                  type={showPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter password"
                  disabled={resetPassword.isPending}
                  className="w-full"
                />
              </div>
            </>
          )}

          {/* Info */}
          <div className="rounded bg-blue-900/20 border border-blue-900/30 p-3">
            <p className="text-xs text-blue-300">
              The user will be required to change their password on their next login.
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            <Button type="submit" disabled={resetPassword.isPending} className="flex-1">
              {resetPassword.isPending ? 'Resetting...' : 'Reset Password'}
            </Button>
            <Button
              type="button"
              onClick={handleClose}
              disabled={resetPassword.isPending}
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
