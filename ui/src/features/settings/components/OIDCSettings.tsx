/**
 * OIDC Settings Component
 * Admin-only OIDC configuration and group mapping interface
 *
 * Group-Based Permissions Refactor (v2.4.0)
 */

import { useState, useEffect } from 'react'
import {
  ExternalLink,
  Plus,
  Trash2,
  Edit2,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Save,
  Key,
  Globe,
  Users,
  AlertTriangle,
} from 'lucide-react'
import {
  useOIDCConfig,
  useUpdateOIDCConfig,
  useDiscoverOIDC,
  useOIDCGroupMappings,
  useCreateOIDCGroupMapping,
  useUpdateOIDCGroupMapping,
  useDeleteOIDCGroupMapping,
} from '@/hooks/useOIDC'
import { useGroups } from '@/hooks/useGroups'
import type {
  OIDCGroupMapping,
  OIDCDiscoveryResponse,
  OIDCConfigUpdateRequest,
} from '@/types/oidc'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'sonner'

// Default OIDC configuration values
const DEFAULT_SCOPES = 'openid profile email groups'
const DEFAULT_GROUPS_CLAIM = 'groups'
const NO_DEFAULT_GROUP = '__none__' // Sentinel value for "no default group"

export function OIDCSettings() {
  const { data: config, isLoading: configLoading, refetch: refetchConfig } = useOIDCConfig()
  const { data: mappings, isLoading: mappingsLoading, refetch: refetchMappings } = useOIDCGroupMappings()
  const { data: groupsData } = useGroups()
  const updateConfig = useUpdateOIDCConfig()
  const discoverOIDC = useDiscoverOIDC()
  const createMapping = useCreateOIDCGroupMapping()
  const updateMapping = useUpdateOIDCGroupMapping()
  const deleteMapping = useDeleteOIDCGroupMapping()

  const groups = groupsData?.groups || []

  // Local form state
  const [enabled, setEnabled] = useState(false)
  const [providerUrl, setProviderUrl] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [scopes, setScopes] = useState(DEFAULT_SCOPES)
  const [claimForGroups, setClaimForGroups] = useState(DEFAULT_GROUPS_CLAIM)
  const [defaultGroupId, setDefaultGroupId] = useState<string>('')
  const [hasChanges, setHasChanges] = useState(false)

  // Discovery state
  const [discoveryResult, setDiscoveryResult] = useState<OIDCDiscoveryResponse | null>(null)

  // Modal states
  const [showCreateMapping, setShowCreateMapping] = useState(false)
  const [editingMapping, setEditingMapping] = useState<OIDCGroupMapping | null>(null)
  const [deletingMapping, setDeletingMapping] = useState<OIDCGroupMapping | null>(null)

  // Sync form state from API
  useEffect(() => {
    if (config) {
      setEnabled(config.enabled)
      setProviderUrl(config.provider_url || '')
      setClientId(config.client_id || '')
      setScopes(config.scopes || DEFAULT_SCOPES)
      setClaimForGroups(config.claim_for_groups || DEFAULT_GROUPS_CLAIM)
      setDefaultGroupId(config.default_group_id?.toString() || NO_DEFAULT_GROUP)
      // Don't sync client_secret - it's never returned
      setHasChanges(false)
    }
  }, [config])

  // Track changes
  useEffect(() => {
    if (!config) return
    const changed =
      enabled !== config.enabled ||
      providerUrl !== (config.provider_url || '') ||
      clientId !== (config.client_id || '') ||
      clientSecret !== '' ||
      scopes !== (config.scopes || DEFAULT_SCOPES) ||
      claimForGroups !== (config.claim_for_groups || DEFAULT_GROUPS_CLAIM) ||
      defaultGroupId !== (config.default_group_id?.toString() || NO_DEFAULT_GROUP)
    setHasChanges(changed)
  }, [config, enabled, providerUrl, clientId, clientSecret, scopes, claimForGroups, defaultGroupId])

  const handleSaveConfig = async () => {
    const data: OIDCConfigUpdateRequest = {}
    if (enabled !== config?.enabled) data.enabled = enabled
    if (providerUrl !== (config?.provider_url || '')) data.provider_url = providerUrl || null
    if (clientId !== (config?.client_id || '')) data.client_id = clientId || null
    if (clientSecret) data.client_secret = clientSecret
    if (scopes !== (config?.scopes || DEFAULT_SCOPES)) data.scopes = scopes || null
    if (claimForGroups !== (config?.claim_for_groups || DEFAULT_GROUPS_CLAIM)) data.claim_for_groups = claimForGroups || null
    if (defaultGroupId !== (config?.default_group_id?.toString() || NO_DEFAULT_GROUP)) {
      data.default_group_id = defaultGroupId && defaultGroupId !== NO_DEFAULT_GROUP ? parseInt(defaultGroupId, 10) : null
    }

    try {
      await updateConfig.mutateAsync(data)
      setClientSecret('')
      setHasChanges(false)
    } catch {
      // Error handled by mutation
    }
  }

  const handleTestConnection = async () => {
    setDiscoveryResult(null)
    try {
      const result = await discoverOIDC.mutateAsync()
      setDiscoveryResult(result)
    } catch {
      // Error handled by mutation
    }
  }

  const isLoading = configLoading || mappingsLoading

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Provider Configuration */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white">OIDC Provider Configuration</h2>
            <p className="mt-1 text-sm text-gray-400">
              Configure your OpenID Connect provider for single sign-on
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Switch
                id="oidc-enabled"
                checked={enabled}
                onCheckedChange={setEnabled}
              />
              <Label htmlFor="oidc-enabled" className="text-sm text-gray-300">
                Enable OIDC
              </Label>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-4 space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="provider-url" className="text-sm text-gray-300">
                Provider URL
              </Label>
              <div className="relative">
                <Globe className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                <Input
                  id="provider-url"
                  placeholder="https://auth.example.com/realms/myrealm"
                  value={providerUrl}
                  onChange={(e) => setProviderUrl(e.target.value)}
                  className="pl-10"
                />
              </div>
              <p className="text-xs text-gray-500">
                Base URL of your OIDC provider (Keycloak, Azure AD, Okta, etc.)
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="client-id" className="text-sm text-gray-300">
                Client ID
              </Label>
              <div className="relative">
                <Key className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                <Input
                  id="client-id"
                  placeholder="dockmon-client"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  className="pl-10"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="client-secret" className="text-sm text-gray-300">
                Client Secret
              </Label>
              <Input
                id="client-secret"
                type="password"
                placeholder={config?.client_secret_configured ? '********' : 'Enter client secret'}
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
              />
              {config?.client_secret_configured && (
                <p className="text-xs text-gray-500">
                  Leave blank to keep existing secret
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="scopes" className="text-sm text-gray-300">
                Scopes
              </Label>
              <Input
                id="scopes"
                placeholder="openid profile email groups"
                value={scopes}
                onChange={(e) => setScopes(e.target.value)}
              />
              <p className="text-xs text-gray-500">
                Space-separated list of OAuth2 scopes
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="claim-for-groups" className="text-sm text-gray-300">
                Groups Claim
              </Label>
              <Input
                id="claim-for-groups"
                placeholder="groups"
                value={claimForGroups}
                onChange={(e) => setClaimForGroups(e.target.value)}
                className="max-w-xs"
              />
              <p className="text-xs text-gray-500">
                The claim in the ID token/userinfo that contains group membership
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="default-group" className="text-sm text-gray-300">
                Default Group
              </Label>
              <Select value={defaultGroupId} onValueChange={setDefaultGroupId}>
                <SelectTrigger className="max-w-xs">
                  <SelectValue placeholder="Select a default group" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">No default (deny access)</SelectItem>
                  {groups.map((group) => (
                    <SelectItem key={group.id} value={group.id.toString()}>
                      {group.name}
                      {group.is_system && ' (System)'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-gray-500">
                Group to assign when no OIDC groups match
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 pt-4 border-t border-gray-800">
            <Button
              onClick={handleSaveConfig}
              disabled={!hasChanges || updateConfig.isPending}
            >
              <Save className="mr-2 h-4 w-4" />
              {updateConfig.isPending ? 'Saving...' : 'Save Configuration'}
            </Button>
            <Button
              variant="outline"
              onClick={handleTestConnection}
              disabled={!providerUrl || discoverOIDC.isPending}
            >
              <ExternalLink className="mr-2 h-4 w-4" />
              {discoverOIDC.isPending ? 'Testing...' : 'Test Connection'}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                refetchConfig()
                refetchMappings()
              }}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
          </div>
        </div>

        {/* Discovery Result */}
        {discoveryResult && (
          <div
            className={`rounded-lg border p-4 ${
              discoveryResult.success
                ? 'border-green-800 bg-green-900/20'
                : 'border-red-800 bg-red-900/20'
            }`}
          >
            <div className="flex items-start gap-3">
              {discoveryResult.success ? (
                <CheckCircle2 className="h-5 w-5 text-green-400 mt-0.5" />
              ) : (
                <XCircle className="h-5 w-5 text-red-400 mt-0.5" />
              )}
              <div className="flex-1 space-y-2">
                <p className={`font-medium ${discoveryResult.success ? 'text-green-300' : 'text-red-300'}`}>
                  {discoveryResult.message}
                </p>
                {discoveryResult.success && (
                  <div className="text-sm text-gray-400 space-y-1">
                    <p><span className="text-gray-500">Issuer:</span> {discoveryResult.issuer}</p>
                    <p><span className="text-gray-500">Authorization:</span> {discoveryResult.authorization_endpoint}</p>
                    <p><span className="text-gray-500">Token:</span> {discoveryResult.token_endpoint}</p>
                    {discoveryResult.scopes_supported && (
                      <p><span className="text-gray-500">Scopes:</span> {discoveryResult.scopes_supported.slice(0, 10).join(', ')}</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Group Mappings */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white">OIDC Group to DockMon Group Mappings</h2>
            <p className="mt-1 text-sm text-gray-400">
              Map OIDC groups to DockMon groups. Higher priority mappings take precedence.
            </p>
          </div>
          <Button onClick={() => setShowCreateMapping(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Add Mapping
          </Button>
        </div>

        <div className="rounded-lg border border-gray-800 bg-gray-900/50 overflow-hidden">
          {mappings && mappings.length > 0 ? (
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-800/50">
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">OIDC Group</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">DockMon Group</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">Priority</th>
                  <th className="px-4 py-3 text-right text-sm font-medium text-gray-400">Actions</th>
                </tr>
              </thead>
              <tbody>
                {mappings.map((mapping) => (
                  <tr key={mapping.id} className="border-b border-gray-800/50 last:border-0">
                    <td className="px-4 py-3">
                      <code className="rounded bg-gray-800 px-2 py-1 text-sm text-blue-300">
                        {mapping.oidc_value}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-900/50 px-2.5 py-0.5 text-xs font-medium text-blue-300">
                        <Users className="h-3 w-3" />
                        {mapping.group_name}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-300">{mapping.priority}</td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setEditingMapping(mapping)}
                          aria-label={`Edit mapping for ${mapping.oidc_value}`}
                        >
                          <Edit2 className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setDeletingMapping(mapping)}
                          className="text-red-400 hover:text-red-300"
                          aria-label={`Delete mapping for ${mapping.oidc_value}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-4 py-8 text-center text-gray-500">
              <Users className="mx-auto h-8 w-8 text-gray-600 mb-2" />
              <p>No group mappings configured</p>
              <p className="text-sm">Users without matching groups will use the default group</p>
            </div>
          )}
        </div>

        {/* Default Group Note */}
        <div className="flex items-start gap-3 rounded-lg border border-yellow-800/50 bg-yellow-900/20 p-4">
          <AlertTriangle className="h-5 w-5 text-yellow-400 mt-0.5" />
          <div className="text-sm">
            <p className="font-medium text-yellow-300">Default Group</p>
            <p className="text-yellow-200/70">
              Users whose OIDC groups don't match any mapping will be assigned to{' '}
              {config?.default_group_name ? (
                <strong>{config.default_group_name}</strong>
              ) : (
                <span>no group (access denied)</span>
              )}
              .
            </p>
          </div>
        </div>
      </section>

      {/* Create Mapping Modal */}
      <GroupMappingModal
        isOpen={showCreateMapping}
        onClose={() => setShowCreateMapping(false)}
        groups={groups}
        onSubmit={async (data) => {
          await createMapping.mutateAsync(data)
          setShowCreateMapping(false)
        }}
        isSubmitting={createMapping.isPending}
      />

      {/* Edit Mapping Modal */}
      <GroupMappingModal
        isOpen={!!editingMapping}
        onClose={() => setEditingMapping(null)}
        mapping={editingMapping}
        groups={groups}
        onSubmit={async (data) => {
          if (!editingMapping) return
          await updateMapping.mutateAsync({ id: editingMapping.id, data })
          setEditingMapping(null)
        }}
        isSubmitting={updateMapping.isPending}
      />

      {/* Delete Confirmation */}
      <Dialog open={!!deletingMapping} onOpenChange={() => setDeletingMapping(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Group Mapping</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete the mapping for <code className="rounded bg-gray-800 px-2 py-1">{deletingMapping?.oidc_value}</code>?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingMapping(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={async () => {
                if (!deletingMapping) return
                await deleteMapping.mutateAsync(deletingMapping.id)
                setDeletingMapping(null)
              }}
              disabled={deleteMapping.isPending}
            >
              {deleteMapping.isPending ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ==================== Helper Components ====================

interface GroupMappingModalProps {
  isOpen: boolean
  onClose: () => void
  mapping?: OIDCGroupMapping | null
  groups: Array<{ id: number; name: string; is_system: boolean }>
  onSubmit: (data: { oidc_value: string; group_id: number; priority: number }) => Promise<void>
  isSubmitting: boolean
}

function GroupMappingModal({ isOpen, onClose, mapping, groups, onSubmit, isSubmitting }: GroupMappingModalProps) {
  const [oidcValue, setOidcValue] = useState('')
  const [groupId, setGroupId] = useState<string>('')
  const [priority, setPriority] = useState(0)

  useEffect(() => {
    if (!isOpen) {
      // Reset form when modal closes
      setOidcValue('')
      setGroupId('')
      setPriority(0)
      return
    }
    if (mapping) {
      setOidcValue(mapping.oidc_value)
      setGroupId(mapping.group_id.toString())
      setPriority(mapping.priority)
    } else {
      setOidcValue('')
      setGroupId('')
      setPriority(0)
    }
  }, [mapping, isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!oidcValue.trim()) {
      toast.error('OIDC group name is required')
      return
    }
    if (!groupId) {
      toast.error('Please select a DockMon group')
      return
    }
    await onSubmit({
      oidc_value: oidcValue.trim(),
      group_id: parseInt(groupId, 10),
      priority,
    })
  }

  return (
    <Dialog open={isOpen} onOpenChange={() => onClose()}>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>{mapping ? 'Edit Group Mapping' : 'Create Group Mapping'}</DialogTitle>
            <DialogDescription>
              Map an OIDC group to a DockMon group. Users with this OIDC group will be assigned to the specified DockMon group.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="oidc-value">OIDC Group Name</Label>
              <Input
                id="oidc-value"
                placeholder="dockmon-admins"
                value={oidcValue}
                onChange={(e) => setOidcValue(e.target.value)}
                required
              />
              <p className="text-xs text-gray-500">
                The exact group name as it appears in your OIDC provider
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="dockmon-group">DockMon Group</Label>
              <Select value={groupId} onValueChange={setGroupId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a group" />
                </SelectTrigger>
                <SelectContent>
                  {groups.map((group) => (
                    <SelectItem key={group.id} value={group.id.toString()}>
                      <span className="flex items-center gap-2">
                        <Users className="h-3 w-3 text-blue-400" />
                        {group.name}
                        {group.is_system && ' (System)'}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="priority">Priority</Label>
              <Input
                id="priority"
                type="number"
                min={0}
                max={1000}
                value={priority}
                onChange={(e) => setPriority(parseInt(e.target.value) || 0)}
              />
              <p className="text-xs text-gray-500">
                Higher priority mappings take precedence when a user has multiple matching OIDC groups
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!oidcValue || !groupId || isSubmitting}>
              {isSubmitting ? 'Saving...' : mapping ? 'Save Changes' : 'Create Mapping'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
