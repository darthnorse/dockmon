/**
 * Container Table Component - Phase 3b/3d
 *
 * FEATURES:
 * - Sortable, filterable table (TanStack Table)
 * - Real-time status updates via WebSocket
 * - Container actions (start/stop/restart)
 * - CPU/Memory sparklines with adaptive polling
 * - Status icons with color coding
 * - Tag chips for container organization
 *
 * PHASE 3d UPDATES:
 * - Status icons instead of badges (per UX spec)
 * - Image:Tag split with tooltip
 * - CPU/Memory sparklines using MiniChart
 * - Network I/O column
 * - Tag chips in host column
 *
 * ARCHITECTURE:
 * - TanStack Table v8 for table logic
 * - TanStack Query for data fetching
 * - Mutation hooks for actions
 * - WebSocket for real-time stats
 */

import { useMemo, useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type ColumnFiltersState,
  type Table,
} from '@tanstack/react-table'

// Extend TanStack Table's ColumnMeta to include our custom align property
declare module '@tanstack/react-table' {
  interface ColumnMeta<TData, TValue> {
    align?: 'left' | 'center' | 'right'
  }
}
import {
  Circle,
  PlayCircle,
  Square,
  RotateCw,
  MoreVertical,
  ArrowUpDown,
  FileText,
  RefreshCw,
  RefreshCwOff,
  Play,
  Clock,
  AlertTriangle,
  Maximize2,
  Package,
} from 'lucide-react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import { POLLING_CONFIG } from '@/lib/config/polling'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { TagChip } from '@/components/TagChip'
import { useAlertCounts, type AlertSeverityCounts } from '@/features/alerts/hooks/useAlerts'
import { AlertDetailsDrawer } from '@/features/alerts/components/AlertDetailsDrawer'
import { ContainerDrawer } from './components/ContainerDrawer'
import { ContainerDetailsModal } from './components/ContainerDetailsModal'
import { BulkActionBar } from './components/BulkActionBar'
import { BulkActionConfirmModal } from './components/BulkActionConfirmModal'
import { BatchJobPanel } from './components/BatchJobPanel'
import type { Container, ContainerAction} from './types'
import { useSimplifiedWorkflow, useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'
import { useContainerUpdateStatus } from './hooks/useContainerUpdates'
import { makeCompositeKey } from '@/lib/utils/containerKeys'

/**
 * Update badge component showing if updates are available
 */
function UpdateBadge({ container, onClick }: { container: Container; onClick?: () => void }) {
  const { data: updateStatus } = useContainerUpdateStatus(container.host_id, container.id)

  if (!updateStatus?.update_available) {
    return null
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        onClick?.()
      }}
      className="relative group p-1 rounded hover:bg-surface-2 transition-colors"
      title="Update available - click to view"
    >
      <Package className="h-4 w-4 text-amber-500" />
      <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded shadow-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 border">
        Update available - click to view
      </div>
    </button>
  )
}

/**
 * Policy icons component showing auto-restart, desired state, and auto-update
 */
function PolicyIcons({ container }: { container: Container }) {
  const isRunning = container.state === 'running'
  const isExited = container.status === 'exited'
  const desiredState = container.desired_state
  const autoRestart = container.auto_restart

  // Get auto-update status
  const { data: updateStatus } = useContainerUpdateStatus(container.host_id, container.id)
  const autoUpdateEnabled = updateStatus?.auto_update_enabled ?? false

  // Determine if we should show warning (desired state is "should_run" but container is exited)
  const showWarning = desiredState === 'should_run' && isExited

  return (
    <div className="flex items-center gap-2">
      {/* Auto-restart icon */}
      <div className="relative group">
        {autoRestart ? (
          <RefreshCw className="h-4 w-4 text-info" />
        ) : (
          <RefreshCwOff className="h-4 w-4 text-muted-foreground" />
        )}
        {/* Tooltip */}
        <div className="invisible group-hover:visible absolute left-1/2 -translate-x-1/2 bottom-full mb-2 z-10 px-2 py-1 text-xs bg-surface-1 border border-border rounded shadow-lg whitespace-nowrap">
          Auto-restart: {autoRestart ? 'Enabled' : 'Disabled'}
        </div>
      </div>

      {/* Desired state icon */}
      <div className="relative group">
        {showWarning ? (
          <AlertTriangle className="h-4 w-4 text-warning" />
        ) : desiredState === 'should_run' ? (
          <Play className={`h-4 w-4 ${isRunning ? 'text-success fill-success' : 'text-foreground'}`} />
        ) : desiredState === 'on_demand' ? (
          <Clock className="h-4 w-4 text-muted-foreground" />
        ) : null}
        {/* Tooltip */}
        {desiredState && desiredState !== 'unspecified' && (
          <div className="invisible group-hover:visible absolute left-1/2 -translate-x-1/2 bottom-full mb-2 z-10 px-2 py-1 text-xs bg-surface-1 border border-border rounded shadow-lg whitespace-nowrap">
            {showWarning ? (
              <span>Should be running but is exited!</span>
            ) : desiredState === 'should_run' ? (
              <span>Desired state: Should Run</span>
            ) : (
              <span>Desired state: On-Demand</span>
            )}
          </div>
        )}
      </div>

      {/* Auto-update icon */}
      {autoUpdateEnabled && (
        <div className="relative group">
          <Package className="h-4 w-4 text-amber-500" />
          {/* Tooltip */}
          <div className="invisible group-hover:visible absolute left-1/2 -translate-x-1/2 bottom-full mb-2 z-10 px-2 py-1 text-xs bg-surface-1 border border-border rounded shadow-lg whitespace-nowrap">
            Auto-update: Enabled
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Status icon with color coding (Phase 3d UX spec)
 * Uses Circle icon with fill for visual consistency
 */
function StatusIcon({ state }: { state: Container['state'] }) {
  const iconMap = {
    running: { color: 'text-success', fill: 'fill-success', label: 'Running', animate: false },
    stopped: { color: 'text-danger', fill: 'fill-danger', label: 'Exited', animate: false },
    exited: { color: 'text-danger', fill: 'fill-danger', label: 'Exited', animate: false },
    created: { color: 'text-muted-foreground', fill: 'fill-muted-foreground', label: 'Created', animate: false },
    paused: { color: 'text-warning', fill: 'fill-warning', label: 'Paused', animate: false },
    restarting: { color: 'text-info', fill: 'fill-info', label: 'Restarting', animate: true },
    removing: { color: 'text-danger', fill: 'fill-danger', label: 'Removing', animate: false },
    dead: { color: 'text-danger', fill: 'fill-danger', label: 'Dead', animate: false },
  }

  const config = iconMap[state] || iconMap.exited

  return (
    <div className="flex items-center gap-2" title={config.label}>
      <Circle
        className={`h-3 w-3 ${config.color} ${config.fill} ${config.animate ? 'animate-spin' : ''}`}
      />
      <span className="text-sm text-muted-foreground">{config.label}</span>
    </div>
  )
}


/**
 * Alert severity counts with color coding and click-to-open-drawer
 */
function ContainerAlertSeverityCounts({
  containerId,
  alertCounts,
  onAlertClick
}: {
  containerId: string
  alertCounts: Map<string, AlertSeverityCounts> | undefined
  onAlertClick: (alertId: string) => void
}) {
  const counts = alertCounts?.get(containerId)

  if (!counts || counts.total === 0) {
    return <span className="text-xs text-muted-foreground">-</span>
  }

  // Get first alert of each severity for click targets
  const getFirstAlertBySeverity = (severity: string) => {
    return counts.alerts.find(a => a.severity.toLowerCase() === severity)?.id
  }

  return (
    <div className="flex items-center gap-1.5 text-xs">
      {counts.critical > 0 && (
        <button
          onClick={() => {
            const alertId = getFirstAlertBySeverity('critical')
            if (alertId) onAlertClick(alertId)
          }}
          className="text-red-500 hover:underline cursor-pointer font-medium"
        >
          {counts.critical}
        </button>
      )}
      {counts.error > 0 && (
        <>
          {counts.critical > 0 && <span className="text-muted-foreground">/</span>}
          <button
            onClick={() => {
              const alertId = getFirstAlertBySeverity('error')
              if (alertId) onAlertClick(alertId)
            }}
            className="text-red-400 hover:underline cursor-pointer font-medium"
          >
            {counts.error}
          </button>
        </>
      )}
      {counts.warning > 0 && (
        <>
          {(counts.critical > 0 || counts.error > 0) && <span className="text-muted-foreground">/</span>}
          <button
            onClick={() => {
              const alertId = getFirstAlertBySeverity('warning')
              if (alertId) onAlertClick(alertId)
            }}
            className="text-yellow-500 hover:underline cursor-pointer font-medium"
          >
            {counts.warning}
          </button>
        </>
      )}
      {counts.info > 0 && (
        <>
          {(counts.critical > 0 || counts.error > 0 || counts.warning > 0) && <span className="text-muted-foreground">/</span>}
          <button
            onClick={() => {
              const alertId = getFirstAlertBySeverity('info')
              if (alertId) onAlertClick(alertId)
            }}
            className="text-blue-400 hover:underline cursor-pointer font-medium"
          >
            {counts.info}
          </button>
        </>
      )}
    </div>
  )
}

/**
 * Updates badge for containers
 */
function ContainerUpdatesBadge({ hasUpdates }: { hasUpdates: boolean }) {
  if (!hasUpdates) {
    return <span className="text-xs text-muted-foreground">-</span>
  }

  return (
    <div className="flex items-center gap-1">
      <div className="h-2 w-2 rounded-full bg-info animate-pulse" />
      <span className="text-xs text-info">Available</span>
    </div>
  )
}


interface ContainerTableProps {
  hostId?: string // Optional: filter by specific host
}

export function ContainerTable({ hostId: propHostId }: ContainerTableProps = {}) {
  const { data: preferences } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const [sorting, setSorting] = useState<SortingState>(preferences?.container_table_sort || [])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [globalFilter, setGlobalFilter] = useState('')
  const [searchParams, setSearchParams] = useSearchParams()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [modalInitialTab, setModalInitialTab] = useState<string>('info')
  const [selectedContainerId, setSelectedContainerId] = useState<string | null>(null)
  const [selectedContainerKey, setSelectedContainerKey] = useState<{ name: string; hostId: string } | null>(null)
  // Use composite keys {host_id}:{container_id} for multi-host support (cloned VMs with same short IDs)
  const [selectedContainerIds, setSelectedContainerIds] = useState<Set<string>>(new Set())
  const [confirmModalOpen, setConfirmModalOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<'start' | 'stop' | 'restart' | null>(null)
  const { enabled: simplifiedWorkflow } = useSimplifiedWorkflow()

  // Initialize sorting from preferences when loaded
  useEffect(() => {
    if (preferences?.container_table_sort) {
      setSorting(preferences.container_table_sort as SortingState)
    }
  }, [preferences?.container_table_sort])

  // Save sorting changes to preferences
  useEffect(() => {
    // Don't save on initial load (empty array)
    if (sorting.length === 0 && !preferences?.container_table_sort) return

    // Debounce to avoid too many updates
    const timer = setTimeout(() => {
      updatePreferences.mutate({ container_table_sort: sorting })
    }, 500)

    return () => clearTimeout(timer)
  }, [sorting])

  // Fetch all alert counts in one batched request
  const { data: alertCounts } = useAlertCounts('container')

  // Alert drawer state
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null)

  const [batchJobId, setBatchJobId] = useState<string | null>(null)
  const [expandedTagsContainerId, setExpandedTagsContainerId] = useState<string | null>(null)

  const queryClient = useQueryClient()

  // Selection handlers
  // containerId should be composite key: {host_id}:{container_id}
  const toggleContainerSelection = (containerId: string) => {
    setSelectedContainerIds(prev => {
      const newSet = new Set(prev)
      if (newSet.has(containerId)) {
        newSet.delete(containerId)
      } else {
        newSet.add(containerId)
      }
      return newSet
    })
  }

  const toggleSelectAll = (table: Table<Container>) => {
    const currentRows = table.getFilteredRowModel().rows
    const currentCompositeKeys = currentRows.map((row) => makeCompositeKey(row.original))

    // Check if all current rows are selected
    const allCurrentSelected = currentCompositeKeys.every((key: string) => selectedContainerIds.has(key))

    if (allCurrentSelected) {
      // Deselect all current rows
      setSelectedContainerIds(prev => {
        const newSet = new Set(prev)
        currentCompositeKeys.forEach((key: string) => newSet.delete(key))
        return newSet
      })
    } else {
      // Select all current rows
      setSelectedContainerIds(prev => {
        const newSet = new Set(prev)
        currentCompositeKeys.forEach((key: string) => newSet.add(key))
        return newSet
      })
    }
  }

  const clearSelection = () => {
    setSelectedContainerIds(new Set())
  }

  const handleBulkAction = (action: 'start' | 'stop' | 'restart') => {
    setPendingAction(action)
    setConfirmModalOpen(true)
  }

  const handleConfirmBulkAction = () => {
    if (!pendingAction) return
    batchMutation.mutate({
      action: pendingAction,
      containerIds: Array.from(selectedContainerIds),
    })
    setConfirmModalOpen(false)
    setPendingAction(null)
  }

  const handleBulkTagUpdate = async (mode: 'add' | 'remove', tags: string[]) => {
    if (!data) return

    const selectedContainers = data.filter((c) => selectedContainerIds.has(makeCompositeKey(c)))
    const action = mode === 'add' ? 'add-tags' : 'remove-tags'

    try {
      // Create batch job for tag update
      const result = await apiClient.post<{ job_id: string }>('/batch', {
        scope: 'container',
        action,
        ids: Array.from(selectedContainerIds), // Send composite keys to backend
        params: { tags },
      })
      setBatchJobId(result.job_id)

      // Show success toast
      const modeText = mode === 'add' ? 'Adding' : 'Removing'
      toast.success(`${modeText} ${tags.length} tag${tags.length !== 1 ? 's' : ''} ${mode === 'remove' ? 'from' : 'to'} ${selectedContainers.length} container${selectedContainers.length !== 1 ? 's' : ''}...`)
    } catch (error) {
      toast.error(`Failed to update tags: ${error instanceof Error ? error.message : 'Unknown error'}`)
      throw error
    }
  }

  const handleBulkAutoRestartUpdate = async (enabled: boolean) => {
    if (!data) return

    const count = selectedContainerIds.size

    try {
      // Create batch job for auto-restart update
      const result = await apiClient.post<{ job_id: string }>('/batch', {
        scope: 'container',
        action: 'set-auto-restart',
        ids: Array.from(selectedContainerIds),
        params: { enabled },
      })
      setBatchJobId(result.job_id)

      toast.success(`${enabled ? 'Enabling' : 'Disabling'} auto-restart for ${count} container${count !== 1 ? 's' : ''}...`)
    } catch (error) {
      toast.error(`Failed to update auto-restart: ${error instanceof Error ? error.message : 'Unknown error'}`)
      throw error
    }
  }

  const handleBulkAutoUpdateUpdate = async (enabled: boolean, floatingTagMode: string) => {
    if (!data) return

    const count = selectedContainerIds.size

    try {
      // Create batch job for auto-update
      const result = await apiClient.post<{ job_id: string }>('/batch', {
        scope: 'container',
        action: 'set-auto-update',
        ids: Array.from(selectedContainerIds),
        params: { enabled, floating_tag_mode: floatingTagMode },
      })
      setBatchJobId(result.job_id)

      const modeText = enabled ? `with ${floatingTagMode} mode` : ''
      toast.success(`${enabled ? 'Enabling' : 'Disabling'} auto-update ${modeText} for ${count} container${count !== 1 ? 's' : ''}...`)
    } catch (error) {
      toast.error(`Failed to update auto-update: ${error instanceof Error ? error.message : 'Unknown error'}`)
      throw error
    }
  }

  const handleBulkDesiredStateUpdate = async (state: 'should_run' | 'on_demand') => {
    if (!data) return

    const count = selectedContainerIds.size

    try {
      // Create batch job for desired state update
      const result = await apiClient.post<{ job_id: string }>('/batch', {
        scope: 'container',
        action: 'set-desired-state',
        ids: Array.from(selectedContainerIds),
        params: { desired_state: state },
      })
      setBatchJobId(result.job_id)

      const stateText = state === 'should_run' ? 'Should Run' : 'On-Demand'
      toast.success(`Setting desired state to "${stateText}" for ${count} container${count !== 1 ? 's' : ''}...`)
    } catch (error) {
      toast.error(`Failed to update desired state: ${error instanceof Error ? error.message : 'Unknown error'}`)
      throw error
    }
  }

  // Filter by hostId from prop or URL params if present
  useEffect(() => {
    const hostId = propHostId || searchParams.get('hostId')
    if (hostId) {
      setColumnFilters([{ id: 'host_id', value: hostId }])
    }
  }, [searchParams, propHostId])

  // Fetch containers with stats
  const { data, isLoading, error } = useQuery<Container[]>({
    queryKey: ['containers'],
    queryFn: () => apiClient.get('/containers'),
    refetchInterval: POLLING_CONFIG.CONTAINER_DATA,
  })

  // Memoize selected container to prevent unnecessary re-renders of modal
  // Use container name + host ID as stable key (survives container recreation during updates)
  const selectedContainer = useMemo(
    () => {
      if (selectedContainerKey) {
        return data?.find((c) => c.name === selectedContainerKey.name && c.host_id === selectedContainerKey.hostId)
      }
      return data?.find((c) => makeCompositeKey(c) === selectedContainerId)
    },
    [data, selectedContainerId, selectedContainerKey]
  )

  // Handle URL param for opening specific container
  useEffect(() => {
    const containerId = searchParams.get('containerId')
    if (containerId && data) {
      const container = data.find(c => c.id === containerId)
      if (container && container.host_id) {
        setSelectedContainerId(makeCompositeKey(container))
        setSelectedContainerKey({ name: container.name, hostId: container.host_id })
        setModalOpen(true)
        // Clear the URL param after opening
        searchParams.delete('containerId')
        setSearchParams(searchParams, { replace: true })
      }
    }
  }, [searchParams, data, setSearchParams])

  // Container action mutation
  const actionMutation = useMutation({
    mutationFn: (action: ContainerAction) =>
      apiClient.post(`/hosts/${action.host_id}/containers/${action.container_id}/${action.type}`, {}),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['containers'] })
      const actionLabel = variables.type.charAt(0).toUpperCase() + variables.type.slice(1)
      // Map action types to proper past tense
      const actionPastTense: Record<string, string> = {
        start: 'started',
        stop: 'stopped',
        restart: 'restarted',
        pause: 'paused',
        unpause: 'unpaused',
        remove: 'removed',
      }
      const pastTense = actionPastTense[variables.type] || `${variables.type}ed`
      toast.success(`Container ${pastTense} successfully`, {
        description: `Action: ${actionLabel}`,
      })
    },
    onError: (error, variables) => {
      debug.error('ContainerTable', `Action ${variables.type} failed:`, error)
      toast.error(`Failed to ${variables.type} container`, {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    },
  })

  // Batch action mutation
  const batchMutation = useMutation({
    mutationFn: ({ action, containerIds }: { action: string; containerIds: string[] }) =>
      apiClient.post<{ job_id: string }>('/batch', {
        scope: 'container',
        action,
        ids: containerIds,
      }),
    onSuccess: (data) => {
      const jobId = data.job_id
      toast.success('Batch job started', {
        description: `Job ID: ${jobId}. Progress will be tracked in the panel.`,
      })
      // Clear selection after starting batch job
      clearSelection()
      // Open batch job progress panel
      setBatchJobId(jobId)
      queryClient.invalidateQueries({ queryKey: ['containers'] })
    },
    onError: (error) => {
      debug.error('ContainerTable', 'Batch action failed:', error)
      toast.error('Failed to start batch job', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    },
  })

  // Table columns (Phase 3d UX spec order)
  const columns = useMemo<ColumnDef<Container>[]>(
    () => [
      // 0. Selection checkbox
      {
        id: 'select',
        header: ({ table }) => {
          const currentRows = table.getFilteredRowModel().rows
          const currentCompositeKeys = currentRows.map(row => makeCompositeKey(row.original))
          const allCurrentSelected = currentCompositeKeys.length > 0 && currentCompositeKeys.every(key => selectedContainerIds.has(key))

          return (
            <div className="flex items-center justify-center">
              <input
                type="checkbox"
                checked={allCurrentSelected}
                onChange={() => toggleSelectAll(table)}
                className="h-4 w-4 rounded border-border text-primary focus:ring-primary cursor-pointer"
              />
            </div>
          )
        },
        cell: ({ row }) => (
          <div className="flex items-center justify-center">
            <input
              type="checkbox"
              checked={selectedContainerIds.has(makeCompositeKey(row.original))}
              onChange={() => toggleContainerSelection(makeCompositeKey(row.original))}
              onClick={(e) => e.stopPropagation()}
              className="h-4 w-4 rounded border-border text-primary focus:ring-primary cursor-pointer"
            />
          </div>
        ),
        size: 50,
        enableSorting: false,
      },
      // 1. Status (icon)
      {
        accessorKey: 'state',
        header: ({ column }) => {
          const sortDirection = column.getIsSorted()
          return (
            <Button
              variant="ghost"
              onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
              className="h-8 px-2 hover:bg-surface-2"
            >
              Status
              <ArrowUpDown className={`ml-2 h-4 w-4 ${sortDirection ? 'text-primary' : 'text-muted-foreground'}`} />
            </Button>
          )
        },
        cell: ({ row }) => <StatusIcon state={row.original.state} />,
      },
      // 2. Name (clickable) with tags
      {
        accessorKey: 'name',
        header: ({ column }) => {
          const sortDirection = column.getIsSorted()
          return (
            <Button
              variant="ghost"
              onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
              className="h-8 px-2 hover:bg-surface-2"
            >
              Name
              <ArrowUpDown className={`ml-2 h-4 w-4 ${sortDirection ? 'text-primary' : 'text-muted-foreground'}`} />
            </Button>
          )
        },
        cell: ({ row }) => {
          const tags = row.original.tags || []
          const visibleTags = tags.slice(0, 3)
          const remainingCount = tags.length - visibleTags.length
          const isExpanded = expandedTagsContainerId === row.original.id

          return (
            <div className="flex flex-col gap-1">
              <button
                className="font-medium text-foreground hover:text-primary transition-colors text-left"
                onClick={() => {
                  setSelectedContainerId(makeCompositeKey(row.original))
                  if (row.original.host_id) {
                    setSelectedContainerKey({ name: row.original.name, hostId: row.original.host_id })
                  }
                  setModalInitialTab('info') // Default to info tab
                  if (simplifiedWorkflow) {
                    setModalOpen(true)
                  } else {
                    setDrawerOpen(true)
                  }
                }}
              >
                {row.original.name || 'Unknown'}
              </button>
              {tags.length > 0 && (
                <div className="flex flex-wrap gap-1 items-center">
                  {visibleTags.map((tag) => (
                    <TagChip
                      key={tag}
                      tag={tag}
                      size="sm"
                      onClick={() => {
                        // Filter by this tag
                        setGlobalFilter(tag)
                      }}
                    />
                  ))}
                  {remainingCount > 0 && (
                    <div className="relative group">
                      <button
                        className="px-2 py-0.5 text-xs rounded-full bg-muted text-muted-foreground font-medium cursor-pointer hover:bg-muted/80 transition-colors"
                        onClick={(e) => {
                          e.stopPropagation()
                          setExpandedTagsContainerId(isExpanded ? null : row.original.id)
                        }}
                      >
                        +{remainingCount}
                      </button>

                      {/* Tooltip on hover - shows vertical list */}
                      {!isExpanded && (
                        <div className="invisible group-hover:visible absolute left-0 bottom-full mb-2 z-30 bg-surface-1 border border-border rounded-lg shadow-xl p-2 min-w-[150px] transition-all delay-300">
                          <div className="flex flex-col gap-1 text-xs text-foreground">
                            {tags.slice(3).map((tag) => (
                              <div key={tag} className="px-2 py-1">
                                {tag}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Dropdown on click - shows clickable chips */}
                      {isExpanded && (
                        <>
                          {/* Backdrop to close dropdown when clicking outside */}
                          <div
                            className="fixed inset-0 z-20"
                            onClick={() => setExpandedTagsContainerId(null)}
                          />
                          {/* Dropdown */}
                          <div className="absolute left-0 top-full mt-1 z-30 bg-surface-1 border border-border rounded-lg shadow-xl p-2 w-[250px]">
                            <div className="flex flex-wrap gap-1">
                              {tags.slice(3).map((tag) => (
                                <TagChip
                                  key={tag}
                                  tag={tag}
                                  size="sm"
                                  onClick={() => {
                                    setGlobalFilter(tag)
                                    setExpandedTagsContainerId(null)
                                  }}
                                />
                              ))}
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        },
      },
      // 3. Policy (auto-restart and desired state)
      {
        id: 'policy',
        header: 'Policy',
        cell: ({ row }) => <PolicyIcons container={row.original} />,
        size: 100,
        enableSorting: false,
      },
      // 4. Alerts
      {
        id: 'alerts',
        header: 'Alerts',
        cell: ({ row }) => (
          <ContainerAlertSeverityCounts
            containerId={row.original.id}
            alertCounts={alertCounts}
            onAlertClick={setSelectedAlertId}
          />
        ),
      },
      // 5. Updates
      {
        id: 'updates',
        header: 'Updates',
        cell: () => <ContainerUpdatesBadge hasUpdates={false} />, // TODO: Check for container updates
      },
      // 6. Host
      {
        accessorKey: 'host_name',
        id: 'host_id',
        header: ({ column }) => {
          const sortDirection = column.getIsSorted()
          return (
            <Button
              variant="ghost"
              onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
              className="h-8 px-2 hover:bg-surface-2"
            >
              Host
              <ArrowUpDown className={`ml-2 h-4 w-4 ${sortDirection ? 'text-primary' : 'text-muted-foreground'}`} />
            </Button>
          )
        },
        filterFn: (row, _columnId, filterValue) => {
          // Filter by host_id when set from URL params
          return row.original.host_id === filterValue
        },
        cell: ({ row }) => (
          <div className="text-sm">{row.original.host_name || 'localhost'}</div>
        ),
      },
      // 7. Uptime (duration)
      {
        accessorKey: 'created',
        header: 'Uptime',
        cell: ({ row }) => {
          const container = row.original

          // Calculate uptime from created timestamp
          const formatUptime = (createdStr: string) => {
            try {
              const created = new Date(createdStr)
              const now = new Date()
              const diffMs = now.getTime() - created.getTime()

              if (diffMs < 0) return '—'

              const seconds = Math.floor(diffMs / 1000)
              const minutes = Math.floor(seconds / 60)
              const hours = Math.floor(minutes / 60)
              const days = Math.floor(hours / 24)

              if (days > 0) {
                return `${days}d ${hours % 24}h`
              } else if (hours > 0) {
                return `${hours}h ${minutes % 60}m`
              } else if (minutes > 0) {
                return `${minutes}m`
              } else {
                return `${seconds}s`
              }
            } catch {
              return '—'
            }
          }

          return (
            <div className="text-sm text-muted-foreground" title={`Created: ${container.created}`}>
              {container.created ? formatUptime(container.created) : '—'}
            </div>
          )
        },
      },
      // 8. CPU%
      {
        id: 'cpu',
        header: 'CPU%',
        cell: ({ row }) => {
          const container = row.original
          if (container.cpu_percent !== undefined && container.cpu_percent !== null) {
            return (
              <span className="text-xs text-muted-foreground">
                {container.cpu_percent.toFixed(1)}%
              </span>
            )
          }
          return <span className="text-xs text-muted-foreground">-</span>
        },
      },
      // 9. RAM (memory usage)
      {
        id: 'memory',
        header: 'RAM',
        cell: ({ row }) => {
          const container = row.original

          if (container.memory_usage === undefined || container.memory_usage === null) {
            return <span className="text-xs text-muted-foreground">-</span>
          }

          const formatMemory = (bytes: number) => {
            const mb = bytes / (1024 * 1024)
            if (mb < 1024) {
              return `${mb.toFixed(0)} MB`
            }
            const gb = mb / 1024
            return `${gb.toFixed(1)} GB`
          }

          const usage = formatMemory(container.memory_usage)
          const limit = container.memory_limit ? formatMemory(container.memory_limit) : '—'

          return (
            <span className="text-xs text-muted-foreground" title={`Limit: ${limit}`}>
              {usage}
            </span>
          )
        },
      },
      // 10. Actions (Start/Stop/Restart/Logs/View details)
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => {
          const container = row.original
          const isRunning = container.state === 'running'
          const isStopped = container.state === 'exited' || container.state === 'stopped' || container.state === 'created'
          const canStart = isStopped && container.host_id
          const canStop = isRunning && container.host_id
          const canRestart = isRunning && container.host_id

          return (
            <div className="flex items-center gap-1">
              {/* Start button - enabled only when stopped */}
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  if (!container.host_id) {
                    toast.error('Cannot start container', {
                      description: 'Container missing host information',
                    })
                    return
                  }
                  actionMutation.mutate({
                    type: 'start',
                    container_id: container.id,
                    host_id: container.host_id,
                  })
                }}
                disabled={!canStart || actionMutation.isPending}
                title="Start container"
              >
                <PlayCircle className={`h-4 w-4 ${canStart ? 'text-success' : 'text-muted-foreground'}`} />
              </Button>

              {/* Stop button - enabled only when running */}
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  if (!container.host_id) {
                    toast.error('Cannot stop container', {
                      description: 'Container missing host information',
                    })
                    return
                  }
                  actionMutation.mutate({
                    type: 'stop',
                    container_id: container.id,
                    host_id: container.host_id,
                  })
                }}
                disabled={!canStop || actionMutation.isPending}
                title="Stop container"
              >
                <Square className={`h-4 w-4 ${canStop ? 'text-danger' : 'text-muted-foreground'}`} />
              </Button>

              {/* Restart button - enabled only when running */}
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  if (!container.host_id) {
                    toast.error('Cannot restart container', {
                      description: 'Container missing host information',
                    })
                    return
                  }
                  actionMutation.mutate({
                    type: 'restart',
                    container_id: container.id,
                    host_id: container.host_id,
                  })
                }}
                disabled={!canRestart || actionMutation.isPending}
                title="Restart container"
              >
                <RotateCw className={`h-4 w-4 ${canRestart ? 'text-info' : 'text-muted-foreground'}`} />
              </Button>

              {/* Maximize button - opens full details modal (hidden in simplified workflow) */}
              {!simplifiedWorkflow && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => {
                    setSelectedContainerId(container.id)
                    if (container.host_id) {
                      setSelectedContainerKey({ name: container.name, hostId: container.host_id })
                    }
                    setModalInitialTab('info') // Default to info tab
                    setModalOpen(true)
                  }}
                  title="View full details"
                >
                  <Maximize2 className="h-4 w-4" />
                </Button>
              )}

              {/* Logs button - always enabled */}
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  setSelectedContainerId(container.id)
                  if (container.host_id) {
                    setSelectedContainerKey({ name: container.name, hostId: container.host_id })
                  }
                  setModalInitialTab('logs')
                  setModalOpen(true)
                }}
                title="View logs"
              >
                <FileText className="h-4 w-4" />
              </Button>

              {/* Update badge - shows if update available */}
              <UpdateBadge
                container={container}
                onClick={() => {
                  setSelectedContainerId(container.id)
                  if (container.host_id) {
                    setSelectedContainerKey({ name: container.name, hostId: container.host_id })
                  }
                  setModalInitialTab('updates')
                  setModalOpen(true)
                }}
              />

              {/* More actions menu */}
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                title="More actions"
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
            </div>
          )
        },
      },
    ],
    [actionMutation, selectedContainerIds, data, toggleContainerSelection, toggleSelectAll, alertCounts]
  )

  const table = useReactTable({
    data: data || [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: (row, _columnId, filterValue) => {
      const searchValue = String(filterValue).toLowerCase()
      const container = row.original

      // Search in container name
      if (container.name?.toLowerCase().includes(searchValue)) {
        return true
      }

      // Search in image
      if (container.image?.toLowerCase().includes(searchValue)) {
        return true
      }

      // Search in host name
      if (container.host_name?.toLowerCase().includes(searchValue)) {
        return true
      }

      // Search in tags array
      if (container.tags?.some(tag => tag.toLowerCase().includes(searchValue))) {
        return true
      }

      return false
    },
    state: {
      sorting,
      columnFilters,
      globalFilter,
    },
  })

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="animate-pulse space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-14 rounded-lg bg-surface-1" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-danger/20 bg-danger/5 p-4">
        <p className="text-sm text-danger">
          Failed to load containers. Please try again.
        </p>
      </div>
    )
  }

  return (
    <div className={`space-y-4 ${selectedContainerIds.size > 0 ? 'pb-[280px]' : ''}`}>
      {/* Search */}
      <div className="flex items-center gap-4">
        <Input
          placeholder="Search containers..."
          value={globalFilter ?? ''}
          onChange={(e) => setGlobalFilter(e.target.value)}
          className="max-w-sm"
          data-testid="containers-search-input"
        />
        <div className="text-sm text-muted-foreground">
          {table.getFilteredRowModel().rows.length} container(s)
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full" data-testid="containers-table">
          <thead className="border-b border-border bg-muted/50 sticky top-0 z-10">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className={`px-4 py-3 text-sm font-medium ${
                      header.column.columnDef.meta?.align === 'center' ? 'text-center' : 'text-left'
                    }`}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-border">
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-8 text-center text-sm text-muted-foreground"
                >
                  No containers found
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-t hover:bg-[#151827] transition-colors"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className={`px-4 py-3 ${
                        cell.column.columnDef.meta?.align === 'center' ? 'text-center' : ''
                      }`}
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Container Drawer */}
      <ContainerDrawer
        isOpen={drawerOpen}
        onClose={() => {
          setDrawerOpen(false)
          setSelectedContainerId(null)
        }}
        containerId={selectedContainerId}
        onExpand={() => {
          setDrawerOpen(false)
          setModalInitialTab('info') // Default to info tab when expanding from drawer
          setModalOpen(true)
        }}
      />

      {/* Container Details Modal */}
      <ContainerDetailsModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false)
          setSelectedContainerId(null)
          setSelectedContainerKey(null)
          setModalInitialTab('info') // Reset to default tab on close
        }}
        containerId={selectedContainerId}
        container={selectedContainer}
        initialTab={modalInitialTab}
      />

      {/* Bulk Action Bar */}
      <BulkActionBar
        selectedCount={selectedContainerIds.size}
        selectedContainers={data?.filter((c) => selectedContainerIds.has(makeCompositeKey(c))) || []}
        onClearSelection={clearSelection}
        onAction={handleBulkAction}
        onTagUpdate={handleBulkTagUpdate}
        onAutoRestartUpdate={handleBulkAutoRestartUpdate}
        onAutoUpdateUpdate={handleBulkAutoUpdateUpdate}
        onDesiredStateUpdate={handleBulkDesiredStateUpdate}
      />

      {/* Bulk Action Confirmation Modal */}
      <BulkActionConfirmModal
        isOpen={confirmModalOpen}
        onClose={() => {
          setConfirmModalOpen(false)
          setPendingAction(null)
        }}
        onConfirm={handleConfirmBulkAction}
        action={pendingAction || 'start'}
        containers={
          data?.filter((c) => selectedContainerIds.has(makeCompositeKey(c))) || []
        }
      />

      {/* Batch Job Progress Panel */}
      <BatchJobPanel
        jobId={batchJobId}
        onClose={() => setBatchJobId(null)}
        bulkActionBarOpen={selectedContainerIds.size > 0}
      />

      {/* Alert Details Drawer */}
      {selectedAlertId && (
        <AlertDetailsDrawer alertId={selectedAlertId} onClose={() => setSelectedAlertId(null)} />
      )}
    </div>
  )
}
