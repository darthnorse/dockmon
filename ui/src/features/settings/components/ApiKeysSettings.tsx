/**
 * API Keys Settings Component
 * Manage API keys for programmatic access (Ansible, Homepage, scripts, etc.)
 *
 * Group-Based Permissions Refactor (v2.4.0)
 */

import { useState } from 'react'
import { Trash2, Edit2, Plus, AlertCircle, Key, AlertTriangle, Users } from 'lucide-react'
import { useApiKeys, useRevokeApiKey } from '@/hooks/useApiKeys'
import { CreateApiKeyModal } from './ApiKeys/CreateApiKeyModal'
import { DisplayNewKeyModal } from './ApiKeys/DisplayNewKeyModal'
import { EditApiKeyModal } from './ApiKeys/EditApiKeyModal'
import { CreateApiKeyResponse } from '@/types/api-keys'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toast } from 'sonner'

export function ApiKeysSettings() {
  const { data: apiKeys, isLoading } = useApiKeys()
  const revokeKey = useRevokeApiKey()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newKey, setNewKey] = useState<CreateApiKeyResponse | null>(null)
  const [editingKeyId, setEditingKeyId] = useState<number | null>(null)
  const [deletingKey, setDeletingKey] = useState<{ id: number; name: string } | null>(null)
  const [showRevoked, setShowRevoked] = useState(false)

  const handleCreateSuccess = (response: CreateApiKeyResponse) => {
    setNewKey(response)
    setShowCreateModal(false)
  }

  const handleCopyKeyToClipboard = () => {
    if (newKey?.key) {
      navigator.clipboard.writeText(newKey.key)
      toast.success('API key copied to clipboard!')
    }
  }

  const handleRevokeClick = (keyId: number, keyName: string) => {
    setDeletingKey({ id: keyId, name: keyName })
  }

  const handleRevokeConfirm = async () => {
    if (!deletingKey) return

    try {
      await revokeKey.mutateAsync(deletingKey.id)
      setDeletingKey(null)
    } catch {
      // Error already handled by mutation
    }
  }

  // Filter keys based on showRevoked toggle
  const filteredKeys = apiKeys?.filter(key => showRevoked || key.revoked_at === null) || []
  const revokedCount = apiKeys?.filter(key => key.revoked_at !== null).length || 0

  return (
    <div className="space-y-6">
      {/* Warning Box */}
      <div className="rounded-lg border border-yellow-900/30 bg-yellow-900/10 p-4">
        <div className="flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-yellow-600 mt-0.5 flex-shrink-0" />
          <div>
            <h3 className="font-semibold text-yellow-200">API keys are sensitive</h3>
            <p className="text-sm text-yellow-300 mt-1">
              API keys grant programmatic access to DockMon. Treat them like passwords and keep them secure. Each key
              is shown only once after creation.
            </p>
          </div>
        </div>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">API Keys</h2>
          <p className="text-sm text-gray-400 mt-1">
            Create API keys for automation tools (Ansible, Homepage, scripts)
          </p>
        </div>
        <Button onClick={() => setShowCreateModal(true)} variant="default" size="sm">
          <Plus className="h-4 w-4 mr-2" />
          Create API Key
        </Button>
      </div>

      {/* Show Revoked Toggle */}
      {revokedCount > 0 && (
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-400 hover:text-gray-300">
            <input
              type="checkbox"
              checked={showRevoked}
              onChange={(e) => setShowRevoked(e.target.checked)}
              className="w-4 h-4 rounded border-gray-700 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-600 focus:ring-offset-0"
            />
            Show revoked keys ({revokedCount})
          </label>
        </div>
      )}

      {/* API Keys List */}
      {isLoading ? (
        <div className="text-center py-8 text-gray-400">Loading API keys...</div>
      ) : !apiKeys || apiKeys.length === 0 ? (
        <div className="rounded-lg border border-gray-800 bg-gray-900/30 p-8 text-center">
          <Key className="h-12 w-12 text-gray-600 mx-auto mb-3" />
          <h3 className="text-gray-400 font-medium">No API keys yet</h3>
          <p className="text-sm text-gray-500 mt-1">Create your first API key to enable programmatic access</p>
        </div>
      ) : filteredKeys.length === 0 ? (
        <div className="rounded-lg border border-gray-800 bg-gray-900/30 p-8 text-center">
          <Key className="h-12 w-12 text-gray-600 mx-auto mb-3" />
          <h3 className="text-gray-400 font-medium">All keys are revoked</h3>
          <p className="text-sm text-gray-500 mt-1">
            Enable "Show revoked keys" to view them, or create a new key
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredKeys.map((key: typeof filteredKeys[0]) => {
            const isRevoked = key.revoked_at !== null
            const isExpired = key.expires_at && new Date(key.expires_at) < new Date()

            return (
              <div
                key={key.id}
                className={`rounded-lg border ${
                  isRevoked ? 'border-red-900/30 bg-red-900/10' : 'border-gray-800 bg-gray-900/50'
                } p-4 hover:bg-gray-900/70 transition-colors`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-white">{key.name}</h3>
                      <code className="text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded">
                        {key.key_prefix}
                      </code>
                      {isRevoked && <span className="text-xs bg-red-900/50 text-red-300 px-2 py-1 rounded">Revoked</span>}
                      {isExpired && (
                        <span className="text-xs bg-yellow-900/50 text-yellow-300 px-2 py-1 rounded">Expired</span>
                      )}
                    </div>
                    {key.description && <p className="text-sm text-gray-400 mt-1">{key.description}</p>}

                    {/* Key Details */}
                    <div className="flex flex-wrap gap-4 mt-3 text-xs text-gray-500">
                      <div className="flex items-center gap-1">
                        <span className="text-gray-400">Group:</span>
                        <Users className="h-3 w-3 text-blue-400" />
                        {key.group_name || 'Unknown'}
                      </div>
                      <div>
                        <span className="text-gray-400">Usage:</span> {key.usage_count} calls
                      </div>
                      {key.last_used_at && (
                        <div>
                          <span className="text-gray-400">Last used:</span>{' '}
                          {new Date(key.last_used_at).toLocaleDateString()}
                        </div>
                      )}
                      {key.expires_at && (
                        <div>
                          <span className="text-gray-400">Expires:</span>{' '}
                          {new Date(key.expires_at).toLocaleDateString()}
                        </div>
                      )}
                      {key.allowed_ips && (
                        <div>
                          <span className="text-gray-400">IP Allowlist:</span> {key.allowed_ips}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  {!isRevoked && (
                    <div className="flex gap-2 ml-4">
                      <button
                        onClick={() => setEditingKeyId(key.id)}
                        className="p-2 hover:bg-gray-700 rounded transition-colors text-gray-400 hover:text-gray-300"
                        title="Edit API key"
                      >
                        <Edit2 className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => handleRevokeClick(key.id, key.name)}
                        disabled={revokeKey.isPending}
                        className="p-2 hover:bg-red-900/30 rounded transition-colors text-red-400 hover:text-red-300 disabled:opacity-50"
                        title="Revoke API key"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Modals */}
      <CreateApiKeyModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSuccess={handleCreateSuccess}
      />

      {newKey && (
        <DisplayNewKeyModal
          isOpen={!!newKey}
          onClose={() => setNewKey(null)}
          keyData={newKey}
          onCopy={handleCopyKeyToClipboard}
        />
      )}

      {editingKeyId && (
        <EditApiKeyModal
          isOpen={!!editingKeyId}
          onClose={() => setEditingKeyId(null)}
          keyId={editingKeyId}
        />
      )}

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deletingKey} onOpenChange={(open) => !open && setDeletingKey(null)}>
        <DialogContent>
          <DialogHeader>
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center h-10 w-10 rounded-full bg-red-900/20">
                <AlertTriangle className="h-5 w-5 text-red-400" />
              </div>
              <div>
                <DialogTitle>Revoke API Key</DialogTitle>
                <DialogDescription className="mt-1">
                  This action cannot be undone. The API key will stop working immediately.
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          {deletingKey && (
            <div className="my-4">
              <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-3">
                <p className="text-sm font-medium text-white">{deletingKey.name}</p>
              </div>
              <p className="text-sm text-gray-400 mt-3">
                All active sessions and integrations using this key will fail immediately. Make sure to update any
                automation or scripts before revoking.
              </p>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingKey(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleRevokeConfirm}
              disabled={revokeKey.isPending}
            >
              {revokeKey.isPending ? 'Revoking...' : 'Revoke API Key'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
