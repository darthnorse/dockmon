/**
 * Create API Key Modal
 * Form to create a new API key with group-based permissions
 *
 * Group-Based Permissions Refactor (v2.4.0)
 */

import { useState, type FormEvent } from 'react'
import { X, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCreateApiKey } from '@/hooks/useApiKeys'
import { useGroups } from '@/hooks/useGroups'
import type { CreateApiKeyResponse, CreateApiKeyRequest } from '@/types/api-keys'
import { toast } from 'sonner'

interface CreateApiKeyModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: (response: CreateApiKeyResponse) => void
}

export function CreateApiKeyModal({ isOpen, onClose, onSuccess }: CreateApiKeyModalProps) {
  const createKey = useCreateApiKey()
  const { data: groupsData, isLoading: loadingGroups, isError: groupsError } = useGroups()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null)
  const [allowedIps, setAllowedIps] = useState('')
  const [expiresDays, setExpiresDays] = useState('')

  const groups = groupsData?.groups || []

  if (!isOpen) return null

  const resetForm = () => {
    setName('')
    setDescription('')
    setSelectedGroupId(null)
    setAllowedIps('')
    setExpiresDays('')
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    if (!name.trim()) {
      toast.error('API key name is required')
      return
    }

    if (!selectedGroupId) {
      toast.error('Select a group for this API key')
      return
    }

    try {
      const request: CreateApiKeyRequest = {
        name: name.trim(),
        group_id: selectedGroupId,
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
      resetForm()
      onSuccess(response)
    } catch {
      // Error handled by mutation
    }
  }

  const handleClose = () => {
    if (createKey.isPending) return
    resetForm()
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
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

          {/* Group Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-3">
              Permissions Group *
            </label>
            <p className="text-xs text-gray-500 mb-3">
              This API key will have the same permissions as the selected group.
            </p>
            {loadingGroups ? (
              <div className="text-sm text-gray-500">Loading groups...</div>
            ) : groupsError ? (
              <div className="rounded-lg border border-red-900/30 bg-red-900/10 p-3 text-sm text-red-300">
                Failed to load groups. Please try again.
              </div>
            ) : groups.length === 0 ? (
              <div className="rounded-lg border border-yellow-900/30 bg-yellow-900/10 p-3 text-sm text-yellow-300">
                No groups available. Create a group first in the Groups settings.
              </div>
            ) : (
              <div className="space-y-2">
                {groups.map((group) => (
                  <label
                    key={group.id}
                    className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                      selectedGroupId === group.id
                        ? 'border-blue-500 bg-blue-900/30'
                        : 'border-gray-700 bg-gray-800/50 hover:border-gray-600'
                    }`}
                  >
                    <input
                      type="radio"
                      name="group"
                      checked={selectedGroupId === group.id}
                      onChange={() => setSelectedGroupId(group.id)}
                      disabled={createKey.isPending}
                      className="mt-0.5 h-4 w-4 border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500"
                    />
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <Users className="h-4 w-4 text-blue-400" />
                        <span className="font-medium text-white">{group.name}</span>
                        {group.is_system && (
                          <span className="rounded bg-gray-700 px-1.5 py-0.5 text-xs text-gray-400">
                            System
                          </span>
                        )}
                      </div>
                      {group.description && (
                        <div className="mt-1 text-xs text-gray-400">{group.description}</div>
                      )}
                    </div>
                  </label>
                ))}
              </div>
            )}
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
