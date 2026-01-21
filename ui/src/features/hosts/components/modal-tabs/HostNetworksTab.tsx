/**
 * HostNetworksTab Component
 *
 * Networks tab for host modal - shows Docker networks with bulk deletion capability
 */

import { useState, useMemo, useCallback, useDeferredValue } from 'react'
import { Search, Trash2, Filter, Shield, Network } from 'lucide-react'
import { useHostNetworks, useDeleteNetwork, useDeleteNetworks, usePruneNetworks } from '../../hooks/useHostNetworks'
import { useSelectionManager } from '@/hooks/useSelectionManager'
import { NetworkDeleteConfirmModal } from '../NetworkDeleteConfirmModal'
import { ConfirmModal } from '@/components/shared/ConfirmModal'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ContainerLinkList } from '@/components/shared/ContainerLinkList'
import { makeCompositeKeyFrom } from '@/lib/utils/containerKeys'
import { pluralize } from '@/lib/utils/formatting'
import type { DockerNetwork } from '@/types/api'

interface HostNetworksTabProps {
  hostId: string
}

function NetworkStatusBadge({ network }: { network: DockerNetwork }) {
  if (network.is_builtin) {
    return (
      <StatusBadge variant="success" icon={<Shield className="h-3 w-3" />}>
        System
      </StatusBadge>
    )
  }
  if (network.container_count > 0) {
    return (
      <StatusBadge variant="success">
        In Use ({network.container_count})
      </StatusBadge>
    )
  }
  return (
    <StatusBadge variant="muted">
      Unused
    </StatusBadge>
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
  const deleteNetworksMutation = useDeleteNetworks()
  const pruneMutation = usePruneNetworks(hostId)

  // UI state
  const [searchQuery, setSearchQuery] = useState('')
  const deferredSearchQuery = useDeferredValue(searchQuery)
  const [showUnusedOnly, setShowUnusedOnly] = useState(false)
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [networksToDelete, setNetworksToDelete] = useState<DockerNetwork[]>([])
  const [showPruneConfirm, setShowPruneConfirm] = useState(false)

  // Filter networks (using deferred search to prevent jank on large lists)
  const filteredNetworks = useMemo(() => {
    if (!networks) return []

    return networks.filter((network) => {
      // Apply unused filter (unused = no containers and not built-in)
      if (showUnusedOnly && (network.container_count > 0 || network.is_builtin)) return false

      // Apply search filter (search in name, driver, or ID)
      if (deferredSearchQuery) {
        const query = deferredSearchQuery.toLowerCase()
        return (
          network.name.toLowerCase().includes(query) ||
          (network.driver || '').toLowerCase().includes(query) ||
          network.id.toLowerCase().includes(query)
        )
      }

      return true
    })
  }, [networks, showUnusedOnly, deferredSearchQuery])

  // Selection management using shared hook (builtin networks not selectable)
  const isNetworkSelectable = useCallback((n: DockerNetwork) => !n.is_builtin, [])
  const getNetworkKey = useCallback((n: DockerNetwork) => n.id, [])

  const {
    selectedCount,
    allSelected,
    toggleSelection,
    toggleSelectAll,
    clearSelection,
    isSelected,
  } = useSelectionManager({
    items: networks,
    filteredItems: filteredNetworks,
    getKey: getNetworkKey,
    isSelectable: isNetworkSelectable,
  })

  // Deletable networks count (for checkbox disabled state)
  const deletableNetworksCount = useMemo(
    () => filteredNetworks.filter(n => !n.is_builtin).length,
    [filteredNetworks]
  )

  // Handle delete button click (single network)
  const handleDeleteClick = useCallback((network: DockerNetwork) => {
    setNetworksToDelete([network])
    setDeleteModalOpen(true)
  }, [])

  // Handle bulk delete button click
  const handleBulkDeleteClick = useCallback(() => {
    if (!networks) return
    const selected = networks.filter(n => isSelected(n.id))
    setNetworksToDelete(selected)
    setDeleteModalOpen(true)
  }, [networks, isSelected])

  // Handle delete confirmation
  const handleDeleteConfirm = useCallback((force: boolean) => {
    if (networksToDelete.length === 0) return

    const firstNetwork = networksToDelete[0]
    if (networksToDelete.length === 1 && firstNetwork) {
      // Single delete
      deleteMutation.mutate({
        hostId,
        networkId: firstNetwork.id,
        networkName: firstNetwork.name,
        force,
      }, {
        onSuccess: () => {
          setDeleteModalOpen(false)
          setNetworksToDelete([])
          // Stale selections cleaned up automatically by useSelectionManager
        },
      })
    } else {
      // Bulk delete
      deleteNetworksMutation.mutate({
        hostId,
        networks: networksToDelete.map(n => ({ id: n.id, name: n.name })),
        force,
      }, {
        onSuccess: () => {
          setDeleteModalOpen(false)
          setNetworksToDelete([])
          // Stale selections cleaned up automatically by useSelectionManager
        },
      })
    }
  }, [networksToDelete, hostId, deleteMutation, deleteNetworksMutation])

  // Count of unused networks (not in use and not built-in)
  const unusedCount = useMemo(() => {
    return networks?.filter((n) => n.container_count === 0 && !n.is_builtin).length ?? 0
  }, [networks])

  // Handle prune confirmation
  const handlePruneConfirm = useCallback(() => {
    pruneMutation.mutate(undefined, {
      onSuccess: () => {
        setShowPruneConfirm(false)
        clearSelection()
      },
      onError: () => setShowPruneConfirm(false),
    })
  }, [pruneMutation, clearSelection])

  const handlePruneClose = useCallback(() => {
    setShowPruneConfirm(false)
  }, [])

  const isPending = deleteMutation.isPending || deleteNetworksMutation.isPending

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 rounded-full border-accent border-t-transparent" />
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
    <div className={`p-6 space-y-4 ${selectedCount > 0 ? 'pb-32' : ''}`}>
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
          {/* Show unused toggle */}
          <button
            onClick={() => setShowUnusedOnly(!showUnusedOnly)}
            className={`flex items-center gap-2 px-3 py-2 text-sm rounded-lg border transition-colors ${
              showUnusedOnly
                ? 'bg-accent text-accent-foreground border-accent'
                : 'bg-surface-2 text-foreground border-border hover:bg-surface-3'
            }`}
          >
            <Filter className="h-4 w-4" />
            Unused Only
            {unusedCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 bg-black/20 rounded text-xs">
                {unusedCount}
              </span>
            )}
          </button>

          {/* Prune button */}
          <button
            onClick={() => setShowPruneConfirm(true)}
            disabled={pruneMutation.isPending || unusedCount === 0}
            className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Trash2 className="h-4 w-4" />
            Prune All Unused
          </button>
        </div>
      </div>

      {/* Network count */}
      <div className="text-sm text-muted-foreground">
        Showing {filteredNetworks.length} of {networks.length} networks
        {selectedCount > 0 && (
          <span className="ml-2 text-accent">({selectedCount} selected)</span>
        )}
      </div>

      {/* Networks table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full table-fixed">
          <thead className="bg-surface-2 border-b border-border">
            <tr>
              <th className="w-10 p-3">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  disabled={deletableNetworksCount === 0}
                  className="w-4 h-4 rounded border-border cursor-pointer disabled:opacity-50"
                />
              </th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Name</th>
              <th className="w-24 text-left p-3 text-sm font-medium text-muted-foreground hidden md:table-cell">Driver</th>
              <th className="w-36 text-left p-3 text-sm font-medium text-muted-foreground hidden md:table-cell">Subnet</th>
              <th className="w-20 text-left p-3 text-sm font-medium text-muted-foreground hidden 2xl:table-cell">Scope</th>
              <th className="w-28 text-left p-3 text-sm font-medium text-muted-foreground">Status</th>
              <th className="w-40 text-left p-3 text-sm font-medium text-muted-foreground hidden xl:table-cell">Containers</th>
              <th className="w-20 p-3 text-sm font-medium text-muted-foreground">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filteredNetworks.map((network) => {
              const selected = isSelected(network.id)

              return (
                <tr
                  key={makeCompositeKeyFrom(hostId, network.id)}
                  className={`hover:bg-surface-2 transition-colors ${selected ? 'bg-accent/5' : ''}`}
                >
                  <td className="p-3">
                    {network.is_builtin ? (
                      <input
                        type="checkbox"
                        disabled
                        className="w-4 h-4 rounded border-border opacity-30 cursor-not-allowed"
                      />
                    ) : (
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => toggleSelection(network.id)}
                        className="w-4 h-4 rounded border-border cursor-pointer"
                      />
                    )}
                  </td>
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
                  <td className="p-3 hidden md:table-cell">
                    <span className="text-sm font-mono text-muted-foreground">
                      {network.subnet || '—'}
                    </span>
                  </td>
                  <td className="p-3 hidden 2xl:table-cell">
                    <span className="text-sm capitalize">{network.scope}</span>
                  </td>
                  <td className="p-3">
                    <NetworkStatusBadge network={network} />
                  </td>
                  <td className="p-3 hidden xl:table-cell">
                    <ContainerLinkList containers={network.containers} hostId={hostId} />
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
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Empty filtered state */}
      {filteredNetworks.length === 0 && networks.length > 0 && (
        <div className="text-center text-muted-foreground py-8">
          No networks match your filters.
        </div>
      )}

      {/* Bulk action bar */}
      {selectedCount > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 bg-surface-1 border-t border-border p-4 shadow-lg">
          <div className="max-w-screen-xl mx-auto flex items-center justify-between">
            <div className="text-sm">
              <span className="font-medium">{selectedCount}</span>
              {' '}{pluralize(selectedCount, 'network')} selected
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={clearSelection}
                className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Clear Selection
              </button>
              <button
                onClick={handleBulkDeleteClick}
                disabled={isPending}
                className="flex items-center gap-2 px-4 py-2 text-sm rounded-lg bg-danger text-danger-foreground hover:bg-danger/90 disabled:opacity-50 transition-colors"
              >
                <Trash2 className="h-4 w-4" />
                Delete Selected
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      <NetworkDeleteConfirmModal
        isOpen={deleteModalOpen}
        onClose={() => {
          setDeleteModalOpen(false)
          setNetworksToDelete([])
        }}
        onConfirm={handleDeleteConfirm}
        network={networksToDelete.length === 1 ? networksToDelete[0] ?? null : null}
        networkCount={networksToDelete.length}
        isPending={isPending}
      />

      <ConfirmModal
        isOpen={showPruneConfirm}
        onClose={handlePruneClose}
        onConfirm={handlePruneConfirm}
        title="Prune Unused Networks"
        description={`This will remove ${unusedCount} unused ${pluralize(unusedCount, 'network')}.`}
        confirmText="Prune Networks"
        pendingText="Pruning..."
        variant="warning"
        isPending={pruneMutation.isPending}
      >
        <p className="text-sm text-muted-foreground">
          Networks that are not connected to any containers will be permanently deleted.
          Built-in networks (bridge, host, none) are never removed.
        </p>
      </ConfirmModal>
    </div>
  )
}
