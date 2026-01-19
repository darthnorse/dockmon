/**
 * HostNetworksTab Component
 *
 * Networks tab for host modal - shows Docker networks with deletion capability
 */

import { useState, useMemo, useCallback } from 'react'
import { Search, Trash2, Filter, Shield, Network } from 'lucide-react'
import { useHostNetworks, useDeleteNetwork } from '../../hooks/useHostNetworks'
import { NetworkDeleteConfirmModal } from '../NetworkDeleteConfirmModal'
import { formatRelativeTime } from '@/lib/utils/eventUtils'
import { makeCompositeKeyFrom } from '@/lib/utils/containerKeys'
import type { DockerNetwork } from '@/types/api'

interface HostNetworksTabProps {
  hostId: string
}

/**
 * Get status badge for a network
 */
function NetworkStatusBadge({ network }: { network: DockerNetwork }) {
  if (network.is_builtin) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-1 bg-success/10 text-success text-xs rounded-full">
        <Shield className="h-3 w-3" />
        System
      </span>
    )
  }
  if (network.container_count > 0) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-1 bg-success/10 text-success text-xs rounded-full">
        In Use ({network.container_count})
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-1 bg-muted/30 text-muted-foreground text-xs rounded-full">
      Unused
    </span>
  )
}

/** Driver-to-color mapping for network badges */
const DRIVER_COLORS: Record<string, string> = {
  bridge: 'bg-accent/10 text-accent',
  overlay: 'bg-info/10 text-info',
}
const DEFAULT_DRIVER_COLOR = 'bg-muted/30 text-muted-foreground'

/**
 * Get driver badge for a network
 */
function NetworkDriverBadge({ driver }: { driver: string }) {
  const colorClass = DRIVER_COLORS[driver?.toLowerCase()] ?? DEFAULT_DRIVER_COLOR

  return (
    <span className={`inline-flex items-center px-2 py-1 text-xs rounded-full ${colorClass}`}>
      {driver || 'default'}
    </span>
  )
}

export function HostNetworksTab({ hostId }: HostNetworksTabProps) {
  const { data: networks, isLoading, error } = useHostNetworks(hostId)
  const deleteMutation = useDeleteNetwork()

  // UI state
  const [searchQuery, setSearchQuery] = useState('')
  const [hideBuiltin, setHideBuiltin] = useState(false)
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [networkToDelete, setNetworkToDelete] = useState<DockerNetwork | null>(null)

  // Filter networks
  const filteredNetworks = useMemo(() => {
    if (!networks) return []

    return networks.filter((network) => {
      // Apply builtin filter
      if (hideBuiltin && network.is_builtin) return false

      // Apply search filter (search in name, driver, or ID)
      if (searchQuery) {
        const query = searchQuery.toLowerCase()
        return (
          network.name.toLowerCase().includes(query) ||
          (network.driver || '').toLowerCase().includes(query) ||
          network.id.toLowerCase().includes(query)
        )
      }

      return true
    })
  }, [networks, hideBuiltin, searchQuery])

  // Handle delete button click
  const handleDeleteClick = useCallback((network: DockerNetwork) => {
    setNetworkToDelete(network)
    setDeleteModalOpen(true)
  }, [])

  // Handle delete confirmation
  const handleDeleteConfirm = useCallback((force: boolean) => {
    if (!networkToDelete) return

    deleteMutation.mutate({
      hostId,
      networkId: networkToDelete.id,
      networkName: networkToDelete.name,
      force,
    }, {
      onSuccess: () => {
        setDeleteModalOpen(false)
        setNetworkToDelete(null)
      },
    })
  }, [networkToDelete, hostId, deleteMutation])

  // Count of user-created networks (non-builtin)
  const userNetworksCount = useMemo(() => {
    return networks?.filter((n) => !n.is_builtin).length ?? 0
  }, [networks])

  // Loading state
  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 border-accent border-t-transparent rounded-full" />
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="p-6">
        <div className="bg-danger/10 text-danger p-4 rounded-lg">
          Failed to load networks: {error.message}
        </div>
      </div>
    )
  }

  // Empty state
  if (!networks || networks.length === 0) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <Network className="h-12 w-12 mx-auto mb-3 opacity-50" />
        No networks found on this host.
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header with search and actions */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search networks..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-surface-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-accent"
          />
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {/* Hide built-in toggle */}
          <button
            onClick={() => setHideBuiltin(!hideBuiltin)}
            className={`flex items-center gap-2 px-3 py-2 text-sm rounded-lg border transition-colors ${
              hideBuiltin
                ? 'bg-accent text-accent-foreground border-accent'
                : 'bg-surface-2 text-foreground border-border hover:bg-surface-3'
            }`}
          >
            <Filter className="h-4 w-4" />
            Hide System
            {userNetworksCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 bg-black/20 rounded text-xs">
                {userNetworksCount}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Network count */}
      <div className="text-sm text-muted-foreground">
        Showing {filteredNetworks.length} of {networks.length} networks
      </div>

      {/* Networks table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-surface-2 border-b border-border">
            <tr>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Name</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden md:table-cell">Driver</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden lg:table-cell">Scope</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden xl:table-cell">Created</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Status</th>
              <th className="w-20 p-3 text-sm font-medium text-muted-foreground">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filteredNetworks.map((network) => (
              <tr
                key={makeCompositeKeyFrom(hostId, network.id)}
                className="hover:bg-surface-2 transition-colors"
              >
                <td className="p-3">
                  <div className="space-y-1">
                    <div className="text-sm font-medium font-mono">
                      {network.name}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono">
                      {network.id}
                    </div>
                    {network.internal && (
                      <span className="inline-flex items-center px-1.5 py-0.5 text-xs rounded bg-muted/30 text-muted-foreground">
                        Internal
                      </span>
                    )}
                  </div>
                </td>
                <td className="p-3 hidden md:table-cell">
                  <NetworkDriverBadge driver={network.driver} />
                </td>
                <td className="p-3 hidden lg:table-cell">
                  <span className="text-sm capitalize">{network.scope}</span>
                </td>
                <td className="p-3 hidden xl:table-cell">
                  <span className="text-sm text-muted-foreground">
                    {formatRelativeTime(network.created)}
                  </span>
                </td>
                <td className="p-3">
                  <NetworkStatusBadge network={network} />
                </td>
                <td className="p-3">
                  {network.is_builtin ? (
                    <button
                      disabled
                      className="p-2 rounded-lg text-muted-foreground/30 cursor-not-allowed"
                      title="Cannot delete system network"
                      aria-label={`Cannot delete system network ${network.name}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  ) : (
                    <button
                      onClick={() => handleDeleteClick(network)}
                      className="p-2 rounded-lg hover:bg-danger/10 text-danger/70 hover:text-danger transition-colors"
                      title="Delete network"
                      aria-label={`Delete network ${network.name}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Empty filtered state */}
      {filteredNetworks.length === 0 && networks.length > 0 && (
        <div className="text-center text-muted-foreground py-8">
          No networks match your filters.
        </div>
      )}

      {/* Delete confirmation modal */}
      <NetworkDeleteConfirmModal
        isOpen={deleteModalOpen}
        onClose={() => {
          setDeleteModalOpen(false)
          setNetworkToDelete(null)
        }}
        onConfirm={handleDeleteConfirm}
        network={networkToDelete}
        isPending={deleteMutation.isPending}
      />
    </div>
  )
}
