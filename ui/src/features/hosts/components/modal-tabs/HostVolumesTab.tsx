/**
 * HostVolumesTab Component
 *
 * Volumes tab for host modal - shows Docker volumes with bulk deletion capability
 */

import { useState, useMemo, useCallback, useEffect, useDeferredValue } from 'react'
import { Search, Trash2, Filter, HardDrive } from 'lucide-react'
import { useHostVolumes, useDeleteVolume, useDeleteVolumes, usePruneVolumes } from '../../hooks/useHostVolumes'
import { VolumeDeleteConfirmModal } from '../VolumeDeleteConfirmModal'
import { ConfirmModal } from '@/components/shared/ConfirmModal'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ContainerLinkList } from '@/components/shared/ContainerLinkList'
import { formatRelativeTime } from '@/lib/utils/eventUtils'
import { pluralize } from '@/lib/utils/formatting'
import type { DockerVolume } from '@/types/api'

interface HostVolumesTabProps {
  hostId: string
}

function VolumeStatusBadge({ volume }: { volume: DockerVolume }) {
  if (volume.in_use) {
    return (
      <StatusBadge variant="success">
        In Use ({volume.container_count})
      </StatusBadge>
    )
  }
  return (
    <StatusBadge variant="muted">
      Unused
    </StatusBadge>
  )
}

export function HostVolumesTab({ hostId }: HostVolumesTabProps) {
  const { data: volumes, isLoading, error } = useHostVolumes(hostId)
  const deleteMutation = useDeleteVolume()
  const deleteVolumesMutation = useDeleteVolumes()
  const pruneMutation = usePruneVolumes(hostId)

  // UI state
  const [searchQuery, setSearchQuery] = useState('')
  const deferredSearchQuery = useDeferredValue(searchQuery)
  const [showUnusedOnly, setShowUnusedOnly] = useState(false)
  const [selectedVolumeNames, setSelectedVolumeNames] = useState<Set<string>>(new Set())
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [volumesToDelete, setVolumesToDelete] = useState<DockerVolume[]>([])
  const [showPruneConfirm, setShowPruneConfirm] = useState(false)

  // Filter volumes (using deferred search to prevent jank on large lists)
  const filteredVolumes = useMemo(() => {
    if (!volumes) return []

    return volumes.filter((volume) => {
      // Apply unused filter
      if (showUnusedOnly && volume.in_use) return false

      // Apply search filter (search in name and driver)
      if (deferredSearchQuery) {
        const query = deferredSearchQuery.toLowerCase()
        return (
          volume.name.toLowerCase().includes(query) ||
          volume.driver.toLowerCase().includes(query)
        )
      }

      return true
    })
  }, [volumes, showUnusedOnly, deferredSearchQuery])

  // Memoize all volume names (for cleaning up stale selections)
  const allVolumeNames = useMemo(
    () => new Set((volumes ?? []).map(v => v.name)),
    [volumes]
  )

  // Clean up stale selections when volumes change
  useEffect(() => {
    setSelectedVolumeNames((prev) => {
      const validNames = new Set([...prev].filter((name) => allVolumeNames.has(name)))
      if (validNames.size !== prev.size) {
        return validNames
      }
      return prev
    })
  }, [allVolumeNames])

  // Check if all filtered volumes are selected
  const allSelected = useMemo(
    () => filteredVolumes.length > 0 && filteredVolumes.every(v => selectedVolumeNames.has(v.name)),
    [filteredVolumes, selectedVolumeNames]
  )

  // Toggle selection for a single volume
  const toggleVolumeSelection = useCallback((volumeName: string) => {
    setSelectedVolumeNames((prev) => {
      const next = new Set(prev)
      if (next.has(volumeName)) {
        next.delete(volumeName)
      } else {
        next.add(volumeName)
      }
      return next
    })
  }, [])

  // Toggle select all (for current filtered volumes)
  const toggleSelectAll = useCallback(() => {
    if (allSelected) {
      // Deselect all current filtered
      setSelectedVolumeNames((prev) => {
        const next = new Set(prev)
        filteredVolumes.forEach(v => next.delete(v.name))
        return next
      })
    } else {
      // Select all current filtered
      setSelectedVolumeNames((prev) => {
        const next = new Set(prev)
        filteredVolumes.forEach(v => next.add(v.name))
        return next
      })
    }
  }, [allSelected, filteredVolumes])

  // Handle delete button click (single volume)
  const handleDeleteClick = useCallback((volume: DockerVolume) => {
    setVolumesToDelete([volume])
    setDeleteModalOpen(true)
  }, [])

  // Handle bulk delete button click
  const handleBulkDeleteClick = useCallback(() => {
    if (!volumes) return
    const selected = volumes.filter(v => selectedVolumeNames.has(v.name))
    setVolumesToDelete(selected)
    setDeleteModalOpen(true)
  }, [volumes, selectedVolumeNames])

  // Handle delete confirmation
  const handleDeleteConfirm = useCallback((force: boolean) => {
    if (volumesToDelete.length === 0) return

    const firstVolume = volumesToDelete[0]
    if (volumesToDelete.length === 1 && firstVolume) {
      // Single delete
      deleteMutation.mutate({
        hostId,
        volumeName: firstVolume.name,
        force,
      }, {
        onSuccess: () => {
          setDeleteModalOpen(false)
          setVolumesToDelete([])
          setSelectedVolumeNames(prev => {
            const next = new Set(prev)
            next.delete(firstVolume.name)
            return next
          })
        },
      })
    } else {
      // Bulk delete
      deleteVolumesMutation.mutate({
        hostId,
        volumes: volumesToDelete.map(v => ({ name: v.name })),
        force,
      }, {
        onSuccess: () => {
          setDeleteModalOpen(false)
          setVolumesToDelete([])
          setSelectedVolumeNames(prev => {
            const next = new Set(prev)
            volumesToDelete.forEach(v => next.delete(v.name))
            return next
          })
        },
      })
    }
  }, [volumesToDelete, hostId, deleteMutation, deleteVolumesMutation])

  // Count of selected volumes
  const selectedCount = selectedVolumeNames.size

  // Count of unused volumes
  const unusedCount = useMemo(() => {
    return volumes?.filter((vol) => !vol.in_use).length ?? 0
  }, [volumes])

  // Handle prune confirmation
  const handlePruneConfirm = useCallback(() => {
    pruneMutation.mutate(undefined, {
      onSuccess: () => {
        setShowPruneConfirm(false)
        setSelectedVolumeNames(new Set())
      },
      onError: () => setShowPruneConfirm(false),
    })
  }, [pruneMutation])

  const handlePruneClose = useCallback(() => {
    setShowPruneConfirm(false)
  }, [])

  const isPending = deleteMutation.isPending || deleteVolumesMutation.isPending

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
          Failed to load volumes: {error.message}
        </div>
      </div>
    )
  }

  // Empty state
  if (!volumes || volumes.length === 0) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <HardDrive className="h-12 w-12 mx-auto mb-3 opacity-50" />
        No volumes found on this host.
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
            placeholder="Search volumes..."
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

      {/* Volume count */}
      <div className="text-sm text-muted-foreground">
        Showing {filteredVolumes.length} of {volumes.length} volumes
        {selectedCount > 0 && (
          <span className="ml-2 text-accent">({selectedCount} selected)</span>
        )}
      </div>

      {/* Volumes table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-surface-2 border-b border-border">
            <tr>
              <th className="w-10 p-3">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  disabled={filteredVolumes.length === 0}
                  className="w-4 h-4 rounded border-border cursor-pointer disabled:opacity-50"
                />
              </th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Name</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden md:table-cell">Driver</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden 2xl:table-cell">Created</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Status</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden xl:table-cell">Containers</th>
              <th className="w-20 p-3 text-sm font-medium text-muted-foreground">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filteredVolumes.map((volume) => {
              const isSelected = selectedVolumeNames.has(volume.name)

              return (
                <tr
                  key={volume.name}
                  className={`hover:bg-surface-2 transition-colors ${isSelected ? 'bg-accent/5' : ''}`}
                >
                  <td className="p-3">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleVolumeSelection(volume.name)}
                      className="w-4 h-4 rounded border-border cursor-pointer"
                    />
                  </td>
                  <td className="p-3">
                    <div className="text-sm font-medium font-mono truncate max-w-[300px]" title={volume.name}>
                      {volume.name}
                    </div>
                  </td>
                  <td className="p-3 hidden md:table-cell">
                    <span className="inline-flex items-center px-2 py-1 text-xs rounded-full bg-muted/30 text-muted-foreground">
                      {volume.driver}
                    </span>
                  </td>
                  <td className="p-3 hidden 2xl:table-cell">
                    <span className="text-sm text-muted-foreground">
                      {formatRelativeTime(volume.created)}
                    </span>
                  </td>
                  <td className="p-3">
                    <VolumeStatusBadge volume={volume} />
                  </td>
                  <td className="p-3 hidden xl:table-cell">
                    <ContainerLinkList containers={volume.containers} hostId={hostId} />
                  </td>
                  <td className="p-3">
                    <button
                      onClick={() => handleDeleteClick(volume)}
                      className="p-2 rounded-lg hover:bg-danger/10 text-danger/70 hover:text-danger transition-colors"
                      title="Delete volume"
                      aria-label={`Delete volume ${volume.name}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Empty filtered state */}
      {filteredVolumes.length === 0 && volumes.length > 0 && (
        <div className="text-center text-muted-foreground py-8">
          No volumes match your filters.
        </div>
      )}

      {/* Bulk action bar */}
      {selectedCount > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 bg-surface-1 border-t border-border p-4 shadow-lg">
          <div className="max-w-screen-xl mx-auto flex items-center justify-between">
            <div className="text-sm">
              <span className="font-medium">{selectedCount}</span>
              {' '}{pluralize(selectedCount, 'volume')} selected
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSelectedVolumeNames(new Set())}
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
      <VolumeDeleteConfirmModal
        isOpen={deleteModalOpen}
        onClose={() => {
          setDeleteModalOpen(false)
          setVolumesToDelete([])
        }}
        onConfirm={handleDeleteConfirm}
        volume={volumesToDelete.length === 1 ? volumesToDelete[0] ?? null : null}
        volumeCount={volumesToDelete.length}
        isPending={isPending}
      />

      <ConfirmModal
        isOpen={showPruneConfirm}
        onClose={handlePruneClose}
        onConfirm={handlePruneConfirm}
        title="Prune Unused Volumes"
        description={`This will remove ${unusedCount} unused ${pluralize(unusedCount, 'volume')}.`}
        confirmText="Prune Volumes"
        pendingText="Pruning..."
        variant="warning"
        isPending={pruneMutation.isPending}
      >
        <p className="text-sm text-muted-foreground">
          Volumes that are not being used by any containers will be permanently deleted.
          This may free up significant disk space but cannot be undone.
        </p>
      </ConfirmModal>
    </div>
  )
}
