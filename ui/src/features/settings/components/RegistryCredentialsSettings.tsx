/**
 * Registry Credentials Settings Component
 * Manage authentication credentials for private container registries
 */

import { useState } from 'react'
import { Trash2, Plus, Edit2, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  useRegistryCredentials,
  useCreateRegistryCredential,
  useUpdateRegistryCredential,
  useDeleteRegistryCredential,
} from '@/hooks/useRegistryCredentials'
import type { RegistryCredential } from '@/types/api'
import { useAuth } from '@/features/auth/AuthContext'

export function RegistryCredentialsSettings() {
  const { hasCapability } = useAuth()
  const canView = hasCapability('registry.view')
  const canManage = hasCapability('registry.manage')
  const { data: credentials, isLoading } = useRegistryCredentials()
  const [showAddModal, setShowAddModal] = useState(false)
  const [editingCredential, setEditingCredential] = useState<RegistryCredential | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  if (!canView) return null

  return (
    <div>
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-foreground">Registry Credentials</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Configure credentials for private container registries
        </p>
      </div>

      {/* Security Notice */}
      <div className="mb-4 rounded-md border border-yellow-900/50 bg-yellow-950/20 px-4 py-3">
        <div className="flex gap-2">
          <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-yellow-200">Security Notice</p>
            <p className="text-xs text-yellow-300/80 mt-1">
              Credentials are encrypted before storage. However, if both the database and encryption
              key are compromised, credentials can be decrypted. See documentation for details.
            </p>
          </div>
        </div>
      </div>

      {/* Credentials Table */}
      <div className="rounded-md border border-border bg-surface-1">
        {isLoading ? (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            Loading credentials...
          </div>
        ) : credentials && credentials.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase">Registry URL</th>
                  <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase">Username</th>
                  <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase">Created</th>
                  <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase w-24">Actions</th>
                </tr>
              </thead>
              <tbody>
                {credentials.map((cred) => (
                  <tr key={cred.id} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-3 text-sm text-foreground font-mono">{cred.registry_url}</td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">{cred.username}</td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">
                      {new Date(cred.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <fieldset disabled={!canManage} className="flex gap-2 disabled:opacity-60">
                        <button
                          onClick={() => setEditingCredential(cred)}
                          className="p-1 text-muted-foreground hover:text-primary transition-colors"
                          title="Edit credential"
                        >
                          <Edit2 className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setDeletingId(cred.id)}
                          className="p-1 text-muted-foreground hover:text-danger transition-colors"
                          title="Delete credential"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </fieldset>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-muted-foreground">No registry credentials configured</p>
            <p className="text-xs text-muted-foreground/70 mt-1">
              Add credentials to authenticate with private container registries
            </p>
          </div>
        )}
      </div>

      {/* Add Credential Button */}
      <div className="mt-4">
        <Button onClick={() => setShowAddModal(true)} variant="outline" size="sm" disabled={!canManage}>
          <Plus className="h-4 w-4 mr-2" />
          Add Credential
        </Button>
      </div>

      {/* Add/Edit Modal */}
      {(showAddModal || editingCredential) && (
        <CredentialModal
          credential={editingCredential}
          disabled={!canManage}
          onClose={() => {
            setShowAddModal(false)
            setEditingCredential(null)
          }}
        />
      )}

      {/* Delete Confirmation */}
      {deletingId !== null && (
        <DeleteConfirmationDialog
          credentialId={deletingId}
          registryUrl={credentials?.find((c) => c.id === deletingId)?.registry_url || ''}
          disabled={!canManage}
          onClose={() => setDeletingId(null)}
        />
      )}
    </div>
  )
}

// ==================== Add/Edit Modal ====================

interface CredentialModalProps {
  credential: RegistryCredential | null
  disabled?: boolean
  onClose: () => void
}

function CredentialModal({ credential, disabled, onClose }: CredentialModalProps) {
  const createMutation = useCreateRegistryCredential()
  const updateMutation = useUpdateRegistryCredential()

  const [registryUrl, setRegistryUrl] = useState(credential?.registry_url || '')
  const [username, setUsername] = useState(credential?.username || '')
  const [password, setPassword] = useState('')

  const isEditing = credential !== null
  const isLoading = createMutation.isPending || updateMutation.isPending

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (isEditing) {
      // Update existing credential
      const data: { username?: string; password?: string } = {}
      if (username !== credential.username) {
        data.username = username
      }
      if (password) {
        data.password = password
      }

      if (Object.keys(data).length === 0) {
        onClose()
        return
      }

      await updateMutation.mutateAsync({ id: credential.id, data })
      onClose()
    } else {
      // Create new credential
      await createMutation.mutateAsync({ registry_url: registryUrl, username, password })
      onClose()
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-surface rounded-lg shadow-xl max-w-md w-full mx-4 border border-border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-border">
          <h3 className="text-lg font-semibold text-foreground">
            {isEditing ? 'Edit Registry Credential' : 'Add Registry Credential'}
          </h3>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          <fieldset disabled={disabled} className="space-y-4 disabled:opacity-60">
          {/* Registry URL */}
          <div>
            <label htmlFor="registry-url" className="block text-sm font-medium text-muted-foreground mb-2">
              Registry URL
            </label>
            <input
              id="registry-url"
              type="text"
              value={registryUrl}
              onChange={(e) => setRegistryUrl(e.target.value)}
              disabled={isEditing}
              placeholder="e.g., ghcr.io, registry.example.com"
              className="w-full rounded-md border border-border bg-surface-1 px-3 py-2 text-foreground placeholder-muted-foreground/50 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
              required={!isEditing}
            />
            {isEditing && (
              <p className="text-xs text-muted-foreground/70 mt-1">Registry URL cannot be changed</p>
            )}
          </div>

          {/* Username */}
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-muted-foreground mb-2">
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Registry username"
              className="w-full rounded-md border border-border bg-surface-1 px-3 py-2 text-foreground placeholder-muted-foreground/50 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              required={!isEditing}
            />
          </div>

          {/* Password */}
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-muted-foreground mb-2">
              {isEditing ? 'New Password (optional)' : 'Password'}
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isEditing ? 'Leave blank to keep current password' : 'Password or access token'}
              className="w-full rounded-md border border-border bg-surface-1 px-3 py-2 text-foreground placeholder-muted-foreground/50 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              required={!isEditing}
            />
          </div>

          {/* Form Actions */}
          <div className="flex gap-3 pt-4">
            <Button type="submit" disabled={isLoading} className="flex-1">
              {isLoading ? 'Saving...' : isEditing ? 'Update' : 'Create'}
            </Button>
            <Button type="button" variant="outline" onClick={onClose} disabled={isLoading}>
              Cancel
            </Button>
          </div>
          </fieldset>
        </form>
      </div>
    </div>
  )
}

// ==================== Delete Confirmation ====================

interface DeleteConfirmationDialogProps {
  credentialId: number
  registryUrl: string
  disabled?: boolean
  onClose: () => void
}

function DeleteConfirmationDialog({ credentialId, registryUrl, disabled, onClose }: DeleteConfirmationDialogProps) {
  const deleteMutation = useDeleteRegistryCredential()

  const handleDelete = async () => {
    await deleteMutation.mutateAsync(credentialId)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-surface rounded-lg shadow-xl max-w-md w-full mx-4 border border-border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-border">
          <h3 className="text-lg font-semibold text-foreground">Delete Registry Credential</h3>
        </div>

        <div className="px-6 py-4">
          <p className="text-sm text-muted-foreground">
            Are you sure you want to delete the credentials for{' '}
            <span className="font-mono text-foreground">{registryUrl}</span>?
          </p>
          <p className="text-xs text-muted-foreground/70 mt-2">
            Update checks for containers using this registry will fail if authentication is required.
          </p>
        </div>

        <fieldset disabled={disabled} className="px-6 py-4 border-t border-border flex gap-3 disabled:opacity-60">
          <Button
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            variant="outline"
            className="flex-1 border-red-900 text-red-400 hover:bg-red-950/50"
          >
            {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
          </Button>
          <Button variant="outline" onClick={onClose} disabled={deleteMutation.isPending}>
            Cancel
          </Button>
        </fieldset>
      </div>
    </div>
  )
}
