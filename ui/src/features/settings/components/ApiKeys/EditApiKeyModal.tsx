/**
 * Edit API Key Modal
 * Allows updating name, description, scopes, and IP restrictions
 */

import { useState, useEffect, type FormEvent } from 'react'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useApiKeys, useUpdateApiKey } from '@/hooks/useApiKeys'
import { ApiKeyScope, UpdateApiKeyRequest, type ApiKey } from '@/types/api-keys'
import { toast } from 'sonner'

interface EditApiKeyModalProps {
  isOpen: boolean
  onClose: () => void
  keyId: number
}

export function EditApiKeyModal({ isOpen, onClose, keyId }: EditApiKeyModalProps) {
  const { data: apiKeys } = useApiKeys()
  const updateKey = useUpdateApiKey()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selectedScopes, setSelectedScopes] = useState<Set<ApiKeyScope>>(new Set())
  const [allowedIps, setAllowedIps] = useState('')

  // Find the key being edited
  const key = (apiKeys || []).find((k: ApiKey) => k.id === keyId)

  // Initialize form with key data
  useEffect(() => {
    if (key) {
      setName(key.name)
      setDescription(key.description || '')
      setSelectedScopes(new Set(key.scopes.split(',') as ApiKeyScope[]))
      setAllowedIps(key.allowed_ips || '')
    }
  }, [key])

  if (!isOpen || !key) return null

  const handleScopeToggle = (scope: ApiKeyScope) => {
    const newScopes = new Set(selectedScopes)
    if (newScopes.has(scope)) {
      newScopes.delete(scope)
    } else {
      newScopes.add(scope)
    }
    setSelectedScopes(newScopes)
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    if (!name.trim()) {
      toast.error('API key name is required')
      return
    }

    if (selectedScopes.size === 0) {
      toast.error('Select at least one scope')
      return
    }

    // Check if anything changed
    const scopesString = Array.from(selectedScopes).sort().join(',')
    const hasChanges =
      name !== key.name ||
      description !== (key.description || '') ||
      scopesString !== key.scopes ||
      allowedIps !== (key.allowed_ips || '')

    if (!hasChanges) {
      onClose()
      return
    }

    try {
      const updateData: UpdateApiKeyRequest = {}

      if (name !== key.name) {
        updateData.name = name.trim()
      }

      if (description !== (key.description || '')) {
        updateData.description = description.trim() || null
      }

      if (scopesString !== key.scopes) {
        updateData.scopes = scopesString
      }

      if (allowedIps !== (key.allowed_ips || '')) {
        updateData.allowed_ips = allowedIps.trim() || null
      }

      await updateKey.mutateAsync({
        keyId,
        data: updateData,
      })
      onClose()
    } catch {
      // Error already handled by mutation
    }
  }

  const handleClose = () => {
    if (updateKey.isPending) return
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-900 rounded-lg max-w-md w-full mx-4 border border-gray-800 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Edit API Key</h2>
          <button onClick={handleClose} disabled={updateKey.isPending} className="text-gray-400 hover:text-gray-300">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">Name *</label>
            <Input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={updateKey.isPending}
              className="w-full"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={updateKey.isPending}
              rows={2}
              className="w-full bg-gray-800 text-white rounded border border-gray-700 px-3 py-2 text-sm focus:border-blue-500 outline-none"
            />
          </div>

          {/* Scopes */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-3">Permissions *</label>
            <div className="space-y-2 p-3 bg-gray-800/50 rounded border border-gray-700">
              {(['read', 'write', 'admin'] as const).map((scope) => (
                <label key={scope} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedScopes.has(scope)}
                    onChange={() => handleScopeToggle(scope)}
                    disabled={updateKey.isPending}
                    className="w-4 h-4"
                  />
                  <span className="text-sm text-gray-300">
                    {scope.charAt(0).toUpperCase() + scope.slice(1)}
                  </span>
                </label>
              ))}
            </div>
            <p className="text-xs text-gray-500 mt-2">
              <strong>read:</strong> View data • <strong>write:</strong> Manage containers •{' '}
              <strong>admin:</strong> Full access
            </p>
          </div>

          {/* IP Allowlist */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">IP Allowlist (Optional)</label>
            <textarea
              value={allowedIps}
              onChange={(e) => setAllowedIps(e.target.value)}
              placeholder="192.168.1.0/24, 10.0.0.1, 203.0.113.5"
              disabled={updateKey.isPending}
              rows={2}
              className="w-full bg-gray-800 text-white rounded border border-gray-700 px-3 py-2 text-sm focus:border-blue-500 outline-none"
            />
            <p className="text-xs text-gray-500 mt-1">Comma-separated IPs or CIDR ranges. Leave empty for unrestricted.</p>
          </div>

          {/* Info */}
          <div className="rounded bg-blue-900/20 border border-blue-900/30 p-3">
            <p className="text-xs text-blue-300">
              <strong>Note:</strong> The API key itself and expiration date cannot be changed. To use a different key or
              extend expiration, create a new key.
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            <Button type="submit" disabled={updateKey.isPending} className="flex-1">
              {updateKey.isPending ? 'Saving...' : 'Save Changes'}
            </Button>
            <Button type="button" onClick={handleClose} disabled={updateKey.isPending} variant="outline" className="flex-1">
              Cancel
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
