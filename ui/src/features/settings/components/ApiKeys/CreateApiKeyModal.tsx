/**
 * Create API Key Modal
 * Form to create a new API key with scope and IP restrictions
 */

import { useState, type FormEvent } from 'react'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCreateApiKey } from '@/hooks/useApiKeys'
import { CreateApiKeyResponse, CreateApiKeyRequest, SCOPE_PRESETS, ApiKeyScope } from '@/types/api-keys'
import { toast } from 'sonner'

interface CreateApiKeyModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: (response: CreateApiKeyResponse) => void
}

export function CreateApiKeyModal({ isOpen, onClose, onSuccess }: CreateApiKeyModalProps) {
  const createKey = useCreateApiKey()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selectedScopes, setSelectedScopes] = useState<Set<ApiKeyScope>>(new Set(['read']))
  const [allowedIps, setAllowedIps] = useState('')
  const [expiresDays, setExpiresDays] = useState('')

  if (!isOpen) return null

  const handleScopePresetClick = (scopes: ApiKeyScope[]) => {
    setSelectedScopes(new Set(scopes))
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

    try {
      const request: CreateApiKeyRequest = {
        name: name.trim(),
        scopes: Array.from(selectedScopes).sort().join(','),
      }

      if (description.trim()) {
        request.description = description.trim()
      }

      if (allowedIps.trim()) {
        request.allowed_ips = allowedIps.trim()
      }

      if (expiresDays) {
        request.expires_days = parseInt(expiresDays, 10)
      }

      const response = await createKey.mutateAsync(request)

      // Reset form
      setName('')
      setDescription('')
      setSelectedScopes(new Set(['read']))
      setAllowedIps('')
      setExpiresDays('')

      // Show new key display modal
      onSuccess(response)
    } catch (error) {
      toast.error('Failed to create API key')
    }
  }

  const handleClose = () => {
    if (createKey.isPending) return
    setName('')
    setDescription('')
    setSelectedScopes(new Set(['read']))
    setAllowedIps('')
    setExpiresDays('')
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-900 rounded-lg max-w-md w-full mx-4 border border-gray-800 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Create API Key</h2>
          <button onClick={handleClose} disabled={createKey.isPending} className="text-gray-400 hover:text-gray-300">
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
              placeholder="e.g., Ansible Automation"
              disabled={createKey.isPending}
              className="w-full"
            />
            <p className="text-xs text-gray-500 mt-1">Descriptive name for this API key</p>
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this key for? (optional)"
              disabled={createKey.isPending}
              rows={2}
              className="w-full bg-gray-800 text-white rounded border border-gray-700 px-3 py-2 text-sm focus:border-blue-500 outline-none"
            />
          </div>

          {/* Scopes */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-3">Permissions *</label>

            {/* Presets */}
            <div className="grid grid-cols-2 gap-2 mb-4">
              {SCOPE_PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  onClick={() => handleScopePresetClick(preset.scopes)}
                  disabled={createKey.isPending}
                  className={`p-3 rounded border text-left transition-colors text-sm ${
                    Array.from(selectedScopes).sort().join(',') === preset.scopes.sort().join(',')
                      ? 'border-blue-500 bg-blue-900/30 text-blue-200'
                      : 'border-gray-700 bg-gray-800/50 text-gray-300 hover:border-gray-600'
                  }`}
                >
                  <div className="font-medium">{preset.label}</div>
                  <div className="text-xs text-gray-400 mt-1">{preset.useCase}</div>
                </button>
              ))}
            </div>

            <p className="text-xs text-gray-500 mt-2">
              <strong>read:</strong> View containers and data • <strong>write:</strong> Manage containers •{' '}
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
              disabled={createKey.isPending}
              rows={2}
              className="w-full bg-gray-800 text-white rounded border border-gray-700 px-3 py-2 text-sm focus:border-blue-500 outline-none"
            />
            <p className="text-xs text-gray-500 mt-1">
              Comma-separated IPs or CIDR ranges. Leave empty for unrestricted access. Requires reverse proxy to work
              correctly.
            </p>
          </div>

          {/* Expiration */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">Expiration (Optional)</label>
            <select
              value={expiresDays}
              onChange={(e) => setExpiresDays(e.target.value)}
              disabled={createKey.isPending}
              className="w-full bg-gray-800 text-white rounded border border-gray-700 px-3 py-2 text-sm focus:border-blue-500 outline-none"
            >
              <option value="">Never expires</option>
              <option value="30">30 days</option>
              <option value="90">90 days</option>
              <option value="180">6 months</option>
              <option value="365">1 year</option>
            </select>
            <p className="text-xs text-gray-500 mt-1">Automatically revokes key after expiration date</p>
          </div>

          {/* Warning */}
          <div className="rounded bg-yellow-900/20 border border-yellow-900/30 p-3">
            <p className="text-xs text-yellow-300">
              <strong>Save the key immediately.</strong> It will only be shown once after creation and cannot be
              retrieved later.
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            <Button
              type="submit"
              disabled={createKey.isPending}
              className="flex-1"
            >
              {createKey.isPending ? 'Creating...' : 'Create API Key'}
            </Button>
            <Button
              type="button"
              onClick={handleClose}
              disabled={createKey.isPending}
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
