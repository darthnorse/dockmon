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

import { useMemo, useState, useEffect, useCallback } from 'react'
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
  ArrowUpDown,
  FileText,
  RefreshCw,
  RefreshCwOff,
  Play,
  Clock,
  AlertTriangle,
  Maximize2,
  Package,
  ExternalLink,
  Activity,
  Filter,
  X,
  ChevronDown,
  Check,
} from 'lucide-react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import { POLLING_CONFIG } from '@/lib/config/polling'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { TagChip } from '@/components/TagChip'
import { DropdownMenu, DropdownMenuSeparator } from '@/components/ui/dropdown-menu'
import { useAlertCounts, type AlertSeverityCounts } from '@/features/alerts/hooks/useAlerts'
import { AlertDetailsDrawer } from '@/features/alerts/components/AlertDetailsDrawer'
import { ContainerDrawer } from './components/ContainerDrawer'
import { BulkActionBar } from './components/BulkActionBar'
import { BulkActionConfirmModal } from './components/BulkActionConfirmModal'
import { DeleteConfirmModal } from './components/DeleteConfirmModal'
import { UpdateConfirmModal } from './components/UpdateConfirmModal'
import { BatchUpdateValidationConfirmModal } from './components/BatchUpdateValidationConfirmModal'
import { BatchJobPanel } from './components/BatchJobPanel'
import { ColumnCustomizationPanel } from './components/ColumnCustomizationPanel'
import { IPAddressCell } from './components/IPAddressCell'
import type { Container } from './types'
import { useSimplifiedWorkflow, useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'
import { useContainerUpdateStatus, useUpdatesSummary, useAllAutoUpdateConfigs, useAllHealthCheckConfigs } from './hooks/useContainerUpdates'
import { useContainerActions } from './hooks/useContainerActions'
import { useContainerHealthCheck } from './hooks/useContainerHealthCheck'
import { makeCompositeKey } from '@/lib/utils/containerKeys'
import { formatBytes } from '@/lib/utils/formatting'
import { useContainerModal } from '@/providers'
import { useHosts } from '@/features/hosts/hooks/useHosts'

/**
 * Update badge component showing if updates are available
 *
 * Performance: Uses batch data from useContainerUpdateStatus (cached) to avoid N+1 queries
 */
function UpdateBadge({
  container,
  onClick,
  updateStatus
}: {
  container: Container
  onClick?: () => void
  updateStatus?: { update_available: boolean } | null | undefined
}) {
  // Fall back to individual hook if batch data not available (shouldn't happen)
  const fallbackQuery = useContainerUpdateStatus(container.host_id, container.id)
  const status = updateStatus ?? fallbackQuery.data

  if (!status?.update_available) {
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
 * Policy icons component showing auto-restart, HTTP health check, desired state, and auto-update
 *
 * Performance: Uses batch data to avoid N+1 queries. Falls back to individual hooks if needed.
 */
function PolicyIcons({
  container,
  autoUpdateConfig,
  healthCheckConfig
}: {
  container: Container
  autoUpdateConfig?: { auto_update_enabled: boolean; floating_tag_mode: string } | null | undefined
  healthCheckConfig?: { enabled: boolean; current_status: string; consecutive_failures: number } | null | undefined
}) {
  const isRunning = container.state === 'running'
  const isExited = container.status === 'exited'
  const desiredState = container.desired_state
  const autoRestart = container.auto_restart

  // Use batch data if available, otherwise fall back to individual hooks
  const fallbackUpdateStatus = useContainerUpdateStatus(container.host_id, container.id)
  const fallbackHealthCheck = useContainerHealthCheck(container.host_id, container.id)

  const autoUpdateEnabled = autoUpdateConfig?.auto_update_enabled ?? fallbackUpdateStatus.data?.auto_update_enabled ?? false
  const healthCheckEnabled = healthCheckConfig?.enabled ?? fallbackHealthCheck.data?.enabled ?? false
  const healthStatus = healthCheckConfig?.current_status ?? fallbackHealthCheck.data?.current_status ?? 'unknown'
  const consecutiveFailures = healthCheckConfig?.consecutive_failures ?? fallbackHealthCheck.data?.consecutive_failures

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

      {/* HTTP Health Check icon */}
      {healthCheckEnabled && (
        <div className="relative group">
          <Activity
            className={`h-4 w-4 ${
              healthStatus === 'healthy'
                ? 'text-success'
                : healthStatus === 'unhealthy'
                ? 'text-danger'
                : 'text-muted-foreground'
            }`}
          />
          {/* Tooltip */}
          <div className="invisible group-hover:visible absolute left-1/2 -translate-x-1/2 bottom-full mb-2 z-10 px-2 py-1 text-xs bg-surface-1 border border-border rounded shadow-lg whitespace-nowrap">
            {healthStatus === 'healthy' && 'HTTP(S) Health Check: Healthy'}
            {healthStatus === 'unhealthy' && (
              <>
                HTTP(S) Health Check: Unhealthy
                {consecutiveFailures && consecutiveFailures > 0 && (
                  <> ({consecutiveFailures} consecutive failures)</>
                )}
              </>
            )}
            {healthStatus === 'unknown' && 'HTTP(S) Health Check: Unknown'}
          </div>
        </div>
      )}

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
  container,
  alertCounts,
  onAlertClick
}: {
  container: Container
  alertCounts: Map<string, AlertSeverityCounts> | undefined
  onAlertClick: (alertId: string) => void
}) {
  // Use composite key to prevent cross-host collisions (cloned VMs with same short IDs)
  const compositeKey = makeCompositeKey(container)
  const counts = alertCounts?.get(compositeKey)

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

interface ContainerTableProps {
  hostId?: string // Optional: filter by specific host
}

export function ContainerTable({ hostId: propHostId }: ContainerTableProps = {}) {
  const { data: preferences } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const [sorting, setSorting] = useState<SortingState>(preferences?.container_table_sort || [])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [globalFilter, setGlobalFilter] = useState('')
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>(preferences?.container_table_column_visibility || {})
  const [columnOrder, setColumnOrder] = useState<string[]>(preferences?.container_table_column_order || [])
  const [searchParams, setSearchParams] = useSearchParams()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedContainerId, setSelectedContainerId] = useState<string | null>(null)
  // Use composite keys {host_id}:{container_id} for multi-host support (cloned VMs with same short IDs)
  const [selectedContainerIds, setSelectedContainerIds] = useState<Set<string>>(new Set())
  const [confirmModalOpen, setConfirmModalOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<'start' | 'stop' | 'restart' | null>(null)
  const [deleteConfirmModalOpen, setDeleteConfirmModalOpen] = useState(false)
  const [updateConfirmModalOpen, setUpdateConfirmModalOpen] = useState(false)
  const [validationModalOpen, setValidationModalOpen] = useState(false)
  const [validationData, setValidationData] = useState<{
    allowed: Array<{ container_id: string; container_name: string; reason: string }>
    warned: Array<{ container_id: string; container_name: string; reason: string; matched_pattern?: string }>
    blocked: Array<{ container_id: string; container_name: string; reason: string }>
  } | null>(null)
  const { enabled: simplifiedWorkflow } = useSimplifiedWorkflow()
  const { openModal } = useContainerModal()

  // Fetch batch configs for filtering and display (replaces N+1 individual queries)
  const { data: allAutoUpdateConfigs } = useAllAutoUpdateConfigs()
  const { data: allHealthCheckConfigs } = useAllHealthCheckConfigs()

  // Parse filters directly from URL params (URL is single source of truth)
  const filters = useMemo(() => {
    const hostParam = searchParams.get('host')
    const stateParam = searchParams.get('state')
    const policyAutoUpdateParam = searchParams.get('policy_auto_update')
    const policyAutoRestartParam = searchParams.get('policy_auto_restart')
    const policyHealthCheckParam = searchParams.get('policy_health_check')
    const updatesParam = searchParams.get('updates')
    const desiredStateParam = searchParams.get('desired_state')

    return {
      selectedHostIds: hostParam ? hostParam.split(',').filter(Boolean) : [],
      selectedStates: stateParam ? stateParam.split(',').filter((s): s is 'running' | 'stopped' => s === 'running' || s === 'stopped') : [] as ('running' | 'stopped')[],
      autoUpdateEnabled: policyAutoUpdateParam === 'enabled' ? true : policyAutoUpdateParam === 'disabled' ? false : null,
      autoRestartEnabled: policyAutoRestartParam === 'enabled' ? true : policyAutoRestartParam === 'disabled' ? false : null,
      healthCheckEnabled: policyHealthCheckParam === 'enabled' ? true : policyHealthCheckParam === 'disabled' ? false : null,
      showUpdatesAvailable: updatesParam === 'true',
      selectedDesiredStates: desiredStateParam ? desiredStateParam.split(',').filter((s): s is 'should_run' | 'on_demand' | 'unspecified' =>
        s === 'should_run' || s === 'on_demand' || s === 'unspecified'
      ) : [] as ('should_run' | 'on_demand' | 'unspecified')[]
    }
  }, [searchParams])

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

  // Initialize column visibility from preferences when loaded
  useEffect(() => {
    if (preferences?.container_table_column_visibility) {
      setColumnVisibility(preferences.container_table_column_visibility)
    }
  }, [preferences?.container_table_column_visibility])

  // Save column visibility changes to preferences
  useEffect(() => {
    // Don't save on initial load (empty object)
    if (Object.keys(columnVisibility).length === 0 && !preferences?.container_table_column_visibility) return

    // Debounce to avoid too many updates
    const timer = setTimeout(() => {
      updatePreferences.mutate({ container_table_column_visibility: columnVisibility })
    }, 500)

    return () => clearTimeout(timer)
  }, [columnVisibility])

  // Initialize column order from preferences when loaded
  useEffect(() => {
    if (preferences?.container_table_column_order && preferences.container_table_column_order.length > 0) {
      // Always ensure 'select' is first (not customizable, always on left)
      const orderWithSelect = ['select', ...preferences.container_table_column_order.filter(id => id !== 'select')]
      setColumnOrder(orderWithSelect)
    }
  }, [preferences?.container_table_column_order])

  // Save column order changes to preferences
  useEffect(() => {
    // Don't save on initial load (empty array)
    if (columnOrder.length === 0 && !preferences?.container_table_column_order) return

    // Remove 'select' before saving (we always add it back on load)
    const orderWithoutSelect = columnOrder.filter(id => id !== 'select')

    // Debounce to avoid too many updates
    const timer = setTimeout(() => {
      updatePreferences.mutate({ container_table_column_order: orderWithoutSelect })
    }, 500)

    return () => clearTimeout(timer)
  }, [columnOrder])

  // Fetch all alert counts in one batched request
  const { data: alertCounts } = useAlertCounts('container')

  // Alert drawer state
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null)

  const [batchJobId, setBatchJobId] = useState<string | null>(null)
  const [showJobPanel, setShowJobPanel] = useState(false)
  const [expandedTagsContainerId, setExpandedTagsContainerId] = useState<string | null>(null)

  const queryClient = useQueryClient()

  // Fetch hosts for filter dropdown
  const { data: hosts } = useHosts()

  // Fetch updates summary for filtering
  const { data: updatesSummary } = useUpdatesSummary()

  // Handle batch job completion - clear both states
  const handleJobComplete = useCallback(() => {
    setBatchJobId(null)
    setShowJobPanel(false)
  }, [])

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

  const handleCheckUpdates = () => {
    batchMutation.mutate({
      action: 'check-updates',
      containerIds: Array.from(selectedContainerIds),
    })
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
      setShowJobPanel(true)

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
      setShowJobPanel(true)

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
      setShowJobPanel(true)

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
      setShowJobPanel(true)

      const stateText = state === 'should_run' ? 'Should Run' : 'On-Demand'
      toast.success(`Setting desired state to "${stateText}" for ${count} container${count !== 1 ? 's' : ''}...`)
    } catch (error) {
      toast.error(`Failed to update desired state: ${error instanceof Error ? error.message : 'Unknown error'}`)
      throw error
    }
  }

  const handleDeleteContainers = () => {
    setDeleteConfirmModalOpen(true)
  }

  const handleConfirmDeleteContainers = async (removeVolumes: boolean) => {
    if (!data) return

    const count = selectedContainerIds.size

    try {
      // Create batch job for container deletion
      const result = await apiClient.post<{ job_id: string }>('/batch', {
        scope: 'container',
        action: 'delete-containers',
        ids: Array.from(selectedContainerIds),
        params: { remove_volumes: removeVolumes },
      })
      setBatchJobId(result.job_id)
      setShowJobPanel(true)
      setDeleteConfirmModalOpen(false)

      toast.success(`Deleting ${count} container${count !== 1 ? 's' : ''}...`)
      clearSelection()
    } catch (error) {
      toast.error(`Failed to delete containers: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  const handleUpdateContainers = async () => {
    if (!data || selectedContainerIds.size === 0) return

    try {
      // Call pre-flight validation endpoint
      const validation = await apiClient.post<{
        allowed: Array<{ container_id: string; container_name: string; reason: string }>
        warned: Array<{ container_id: string; container_name: string; reason: string; matched_pattern?: string }>
        blocked: Array<{ container_id: string; container_name: string; reason: string }>
        summary: { total: number; allowed: number; warned: number; blocked: number }
      }>('/batch/validate-update', {
        container_ids: Array.from(selectedContainerIds),
      })

      // If there are warned or blocked containers, show validation modal
      if (validation.warned.length > 0 || validation.blocked.length > 0) {
        setValidationData(validation)
        setValidationModalOpen(true)
      } else {
        // All containers allowed - show simple confirmation
        setUpdateConfirmModalOpen(true)
      }
    } catch (error) {
      debug.error('ContainerTable', 'Failed to validate batch update:', error)
      toast.error(`Failed to validate update: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  const handleConfirmUpdateContainers = async () => {
    if (!data) return

    const count = selectedContainerIds.size

    try {
      // Create batch job for container updates
      const result = await apiClient.post<{ job_id: string }>('/batch', {
        scope: 'container',
        action: 'update-containers',
        ids: Array.from(selectedContainerIds),
      })
      setBatchJobId(result.job_id)
      setShowJobPanel(true)
      setUpdateConfirmModalOpen(false)

      toast.success(`Updating ${count} container${count !== 1 ? 's' : ''}...`)
      clearSelection()
    } catch (error) {
      toast.error(`Failed to update containers: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  const handleConfirmValidatedUpdate = async () => {
    if (!data || !validationData) return

    // Extract non-blocked container IDs (allowed + warned)
    const allowedIds = new Set(validationData.allowed.map(c => c.container_id))
    const warnedIds = new Set(validationData.warned.map(c => c.container_id))
    const updateIds = [...allowedIds, ...warnedIds]

    try {
      // Create batch job with force_warn parameter
      const result = await apiClient.post<{ job_id: string }>('/batch', {
        scope: 'container',
        action: 'update-containers',
        ids: updateIds,
        params: {
          force_warn: true, // Allow warned containers to update
        },
      })
      setBatchJobId(result.job_id)
      setShowJobPanel(true)
      setValidationModalOpen(false)
      setValidationData(null)

      toast.success(`Updating ${updateIds.length} container${updateIds.length !== 1 ? 's' : ''}...`)
      clearSelection()
    } catch (error) {
      toast.error(`Failed to update containers: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  // Handle legacy propHostId (integrate into new filter system)
  useEffect(() => {
    if (propHostId && !filters.selectedHostIds.includes(propHostId)) {
      const params = new URLSearchParams(searchParams)
      params.set('host', propHostId)
      setSearchParams(params, { replace: true })
    }
    // Note: setSearchParams is stable, searchParams changes are captured via filters.selectedHostIds
  }, [propHostId, filters.selectedHostIds])

  // Fetch containers with stats
  const { data, isLoading, error } = useQuery<Container[]>({
    queryKey: ['containers'],
    queryFn: () => apiClient.get('/containers'),
    refetchInterval: POLLING_CONFIG.CONTAINER_DATA,
  })

  // Container action hook (reusable across components)
  const { executeAction, isPending: isActionPending } = useContainerActions({
    invalidateQueries: ['containers'],
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
      setShowJobPanel(true)
      queryClient.invalidateQueries({ queryKey: ['containers'] })
    },
    onError: (error) => {
      debug.error('ContainerTable', 'Batch action failed:', error)
      toast.error('Failed to start batch job', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    },
  })

  // Apply custom filters to container data
  // Performance: Uses batch data from useAllAutoUpdateConfigs and useAllHealthCheckConfigs
  // to avoid N+1 queries (single API call instead of N individual calls)
  const filteredData = useMemo(() => {
    if (!data) return []

    return data.filter((container) => {
      // Host filter (multi-select)
      if (filters.selectedHostIds.length > 0 && (!container.host_id || !filters.selectedHostIds.includes(container.host_id))) {
        return false
      }

      // State filter (multi-select)
      if (filters.selectedStates.length > 0) {
        const containerState = container.state === 'running' ? 'running' : 'stopped'
        if (!filters.selectedStates.includes(containerState)) {
          return false
        }
      }

      // Auto-restart filter (boolean) - directly available on container
      if (filters.autoRestartEnabled !== null) {
        const hasAutoRestart = container.auto_restart ?? false
        if (hasAutoRestart !== filters.autoRestartEnabled) {
          return false
        }
      }

      // Desired State filter (multi-select)
      if (filters.selectedDesiredStates.length > 0) {
        const containerDesiredState = container.desired_state || 'unspecified'
        if (!filters.selectedDesiredStates.includes(containerDesiredState)) {
          return false
        }
      }

      // Updates Available filter
      if (filters.showUpdatesAvailable) {
        const compositeKey = makeCompositeKey(container)
        const hasUpdate = updatesSummary?.containers_with_updates?.includes(compositeKey) ?? false
        if (!hasUpdate) {
          return false
        }
      }

      // Auto-update filter (uses batch data - no N+1 queries!)
      if (filters.autoUpdateEnabled !== null && allAutoUpdateConfigs) {
        const compositeKey = makeCompositeKey(container)
        const config = allAutoUpdateConfigs[compositeKey]
        const hasAutoUpdate = config?.auto_update_enabled ?? false
        if (hasAutoUpdate !== filters.autoUpdateEnabled) {
          return false
        }
      }

      // Health check filter (uses batch data - no N+1 queries!)
      if (filters.healthCheckEnabled !== null && allHealthCheckConfigs) {
        const compositeKey = makeCompositeKey(container)
        const config = allHealthCheckConfigs[compositeKey]
        const hasHealthCheck = config?.enabled ?? false
        if (hasHealthCheck !== filters.healthCheckEnabled) {
          return false
        }
      }

      return true
    })
  }, [data, filters, updatesSummary, allAutoUpdateConfigs, allHealthCheckConfigs])

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
                  const compositeKey = makeCompositeKey(row.original)
                  if (simplifiedWorkflow) {
                    // Open global modal directly
                    openModal(compositeKey, 'info')
                  } else {
                    // Open drawer (keeps local state for drawer)
                    setSelectedContainerId(compositeKey)
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
      // 3. Policy (auto-restart, health check, desired state, auto-update)
      {
        id: 'policy',
        header: 'Policy',
        cell: ({ row }) => {
          const compositeKey = makeCompositeKey(row.original)
          return (
            <PolicyIcons
              container={row.original}
              autoUpdateConfig={allAutoUpdateConfigs?.[compositeKey]}
              healthCheckConfig={allHealthCheckConfigs?.[compositeKey]}
            />
          )
        },
        size: 120,
        enableSorting: false,
      },
      // 4. Alerts
      {
        id: 'alerts',
        header: ({ column }) => {
          const sortDirection = column.getIsSorted()
          return (
            <Button
              variant="ghost"
              onClick={() => column.toggleSorting(sortDirection === 'asc')}
              className="h-8 px-2 hover:bg-surface-2"
            >
              Alerts
              <ArrowUpDown className={`ml-2 h-4 w-4 ${sortDirection ? 'text-primary' : 'text-muted-foreground'}`} />
            </Button>
          )
        },
        accessorFn: (row) => {
          // Calculate total alert count for sorting
          const compositeKey = makeCompositeKey(row)
          const counts = alertCounts?.get(compositeKey)
          if (!counts) return 0
          return counts.critical + counts.error + counts.warning + counts.info
        },
        cell: ({ row }) => (
          <ContainerAlertSeverityCounts
            container={row.original}
            alertCounts={alertCounts}
            onAlertClick={setSelectedAlertId}
          />
        ),
        enableSorting: true,
      },
      // 5. Host
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
        cell: ({ row }) => {
          const { host_name } = row.original
          return <div className="text-sm">{host_name || 'localhost'}</div>
        },
      },
      // 7. IP Address (Docker network IPs)
      {
        id: 'ip',
        header: 'IP Address',
        cell: ({ row }) => <IPAddressCell container={row.original} />,
        size: 150,
        enableSorting: false,
      },
      // 8. Ports
      {
        accessorKey: 'ports',
        id: 'ports',
        header: 'Ports',
        cell: ({ row }) => {
          const container = row.original
          if (!container.ports || container.ports.length === 0) {
            return <span className="text-xs text-muted-foreground">-</span>
          }

          // Display all ports as comma-separated list
          return (
            <div className="text-xs text-muted-foreground">
              {container.ports.join(', ')}
            </div>
          )
        },
        enableSorting: false,
      },
      // 8. Uptime (duration)
      {
        accessorKey: 'created',
        header: ({ column }) => {
          const sortDirection = column.getIsSorted()
          return (
            <Button
              variant="ghost"
              onClick={() => column.toggleSorting(sortDirection === 'asc')}
              className="h-8 px-2 hover:bg-surface-2"
            >
              Uptime
              <ArrowUpDown className={`ml-2 h-4 w-4 ${sortDirection ? 'text-primary' : 'text-muted-foreground'}`} />
            </Button>
          )
        },
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
        enableSorting: true,
      },
      // 9. CPU%
      {
        id: 'cpu',
        header: ({ column }) => {
          const sortDirection = column.getIsSorted()
          return (
            <Button
              variant="ghost"
              onClick={() => column.toggleSorting(sortDirection === 'asc')}
              className="h-8 px-2 hover:bg-surface-2"
            >
              CPU%
              <ArrowUpDown className={`ml-2 h-4 w-4 ${sortDirection ? 'text-primary' : 'text-muted-foreground'}`} />
            </Button>
          )
        },
        accessorFn: (row) => row.cpu_percent ?? -1,
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
        enableSorting: true,
      },
      // 10. RAM (memory usage)
      {
        id: 'memory',
        header: ({ column }) => {
          const sortDirection = column.getIsSorted()
          return (
            <Button
              variant="ghost"
              onClick={() => column.toggleSorting(sortDirection === 'asc')}
              className="h-8 px-2 hover:bg-surface-2"
            >
              RAM
              <ArrowUpDown className={`ml-2 h-4 w-4 ${sortDirection ? 'text-primary' : 'text-muted-foreground'}`} />
            </Button>
          )
        },
        accessorFn: (row) => row.memory_usage ?? -1,
        cell: ({ row }) => {
          const container = row.original

          if (container.memory_usage === undefined || container.memory_usage === null) {
            return <span className="text-xs text-muted-foreground">-</span>
          }

          const usage = formatBytes(container.memory_usage)
          const limit = container.memory_limit ? formatBytes(container.memory_limit) : 'No limit'

          return (
            <span className="text-xs text-muted-foreground" title={`Limit: ${limit}`}>
              {usage}
            </span>
          )
        },
        enableSorting: true,
      },
      // 11. Actions (Start/Stop/Restart/Logs/View details)
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
                  executeAction({
                    type: 'start',
                    container_id: container.id,
                    host_id: container.host_id,
                  })
                }}
                disabled={!canStart || isActionPending}
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
                  executeAction({
                    type: 'stop',
                    container_id: container.id,
                    host_id: container.host_id,
                  })
                }}
                disabled={!canStop || isActionPending}
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
                  executeAction({
                    type: 'restart',
                    container_id: container.id,
                    host_id: container.host_id,
                  })
                }}
                disabled={!canRestart || isActionPending}
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
                    openModal(makeCompositeKey(container), 'info')
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
                  openModal(makeCompositeKey(container), 'logs')
                }}
                title="View logs"
              >
                <FileText className="h-4 w-4" />
              </Button>

              {/* Update badge - shows if update available */}
              <UpdateBadge
                container={container}
                onClick={() => {
                  openModal(makeCompositeKey(container), 'updates')
                }}
              />

              {/* WebUI link - shows if web_ui_url is defined */}
              {container.web_ui_url && (
                <a
                  href={container.web_ui_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center justify-center h-8 w-8 rounded hover:bg-surface-2 text-muted-foreground hover:text-primary transition-colors"
                  title="Open WebUI"
                  onClick={(e) => e.stopPropagation()}
                >
                  <ExternalLink className="h-4 w-4" />
                </a>
              )}
            </div>
          )
        },
      },
    ],
    [executeAction, isActionPending, selectedContainerIds, data, toggleContainerSelection, toggleSelectAll, alertCounts, allAutoUpdateConfigs, allHealthCheckConfigs]
  )

  const table = useReactTable({
    data: filteredData || [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    onColumnVisibilityChange: setColumnVisibility,
    onColumnOrderChange: setColumnOrder,
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

      // Search in ports array (e.g., ["8080:80/tcp", "443:443/tcp"])
      if (container.ports?.some(port => port.toLowerCase().includes(searchValue))) {
        return true
      }

      // Search in primary IP address
      if (container.docker_ip?.toLowerCase().includes(searchValue)) {
        return true
      }

      // Search in all IP addresses (for multi-network containers)
      if (container.docker_ips) {
        const ipMatches = Object.values(container.docker_ips).some(ip =>
          ip.toLowerCase().includes(searchValue)
        )
        if (ipMatches) {
          return true
        }
      }

      return false
    },
    state: {
      sorting,
      columnFilters,
      globalFilter,
      columnVisibility,
      columnOrder,
    },
  })

  // Filter toggle handlers - update URL directly (URL is source of truth)
  const toggleHostFilter = (hostId: string) => {
    const params = new URLSearchParams(searchParams)
    const current = filters.selectedHostIds
    const newHosts = current.includes(hostId)
      ? current.filter(id => id !== hostId)
      : [...current, hostId]

    if (newHosts.length > 0) {
      params.set('host', newHosts.join(','))
    } else {
      params.delete('host')
    }
    setSearchParams(params, { replace: true })
  }

  const toggleStateFilter = (state: 'running' | 'stopped') => {
    const params = new URLSearchParams(searchParams)
    const current = filters.selectedStates
    const newStates = current.includes(state)
      ? current.filter(s => s !== state)
      : [...current, state]

    if (newStates.length > 0) {
      params.set('state', newStates.join(','))
    } else {
      params.delete('state')
    }
    setSearchParams(params, { replace: true })
  }

  const toggleDesiredStateFilter = (state: 'should_run' | 'on_demand' | 'unspecified') => {
    const params = new URLSearchParams(searchParams)
    const current = filters.selectedDesiredStates
    const newStates = current.includes(state)
      ? current.filter(s => s !== state)
      : [...current, state]

    if (newStates.length > 0) {
      params.set('desired_state', newStates.join(','))
    } else {
      params.delete('desired_state')
    }
    setSearchParams(params, { replace: true })
  }

  const togglePolicyFilter = (
    policy: 'auto_update' | 'auto_restart' | 'health_check',
    value: boolean
  ) => {
    const params = new URLSearchParams(searchParams)

    const paramNames = {
      auto_update: 'policy_auto_update',
      auto_restart: 'policy_auto_restart',
      health_check: 'policy_health_check',
    }

    const currentValues = {
      auto_update: filters.autoUpdateEnabled,
      auto_restart: filters.autoRestartEnabled,
      health_check: filters.healthCheckEnabled,
    }

    const currentValue = currentValues[policy]
    const paramName = paramNames[policy]

    // Mutual exclusivity: clicking same value clears, clicking opposite value toggles
    if (currentValue === value) {
      params.delete(paramName) // Clear filter
    } else {
      params.set(paramName, value ? 'enabled' : 'disabled') // Set to new value
    }
    setSearchParams(params, { replace: true })
  }

  const clearAllFilters = () => {
    setSearchParams(new URLSearchParams(), { replace: true })
  }

  const hasActiveFilters =
    filters.selectedHostIds.length > 0 ||
    filters.selectedStates.length > 0 ||
    filters.autoUpdateEnabled !== null ||
    filters.autoRestartEnabled !== null ||
    filters.healthCheckEnabled !== null ||
    filters.showUpdatesAvailable ||
    filters.selectedDesiredStates.length > 0

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
      {/* Search and Filters */}
      <div className="flex items-center justify-between gap-4">
        {/* Left: Search */}
        <div className="flex items-center gap-4">
          <Input
            placeholder="Search containers..."
            value={globalFilter ?? ''}
            onChange={(e) => setGlobalFilter(e.target.value)}
            className="max-w-md"
            data-testid="containers-search-input"
          />
          <div className="text-sm text-muted-foreground whitespace-nowrap">
            {table.getFilteredRowModel().rows.length} container(s)
          </div>
        </div>

        {/* Right: Filter dropdowns */}
        <div className="flex items-center gap-2">
          {/* Clear Filters Button */}
          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={clearAllFilters}
              className="h-9 text-xs"
            >
              <X className="h-3.5 w-3.5 mr-1" />
              Clear Filters
            </Button>
          )}

          {/* Hosts Filter */}
          <DropdownMenu
            trigger={
              <Button variant="outline" size="sm" className="h-9">
                <Filter className="h-3.5 w-3.5 mr-2" />
                Hosts
                {filters.selectedHostIds.length > 0 && (
                  <span className="ml-1.5 px-1.5 py-0.5 text-xs bg-primary/20 text-primary rounded">
                    {filters.selectedHostIds.length}
                  </span>
                )}
                <ChevronDown className="h-3.5 w-3.5 ml-2" />
              </Button>
            }
            align="end"
          >
            <div className="max-h-[300px] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
              {hosts && hosts.length > 0 ? (
                hosts.map((host) => (
                  <div
                    key={host.id}
                    className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                    onClick={() => toggleHostFilter(host.id)}
                  >
                    <div className="w-4 h-4 flex items-center justify-center">
                      {filters.selectedHostIds.includes(host.id) && (
                        <Check className="h-3.5 w-3.5 text-primary" />
                      )}
                    </div>
                    <span className="text-xs">{host.name}</span>
                  </div>
                ))
              ) : (
                <div className="px-2 py-2 text-xs text-muted-foreground">No hosts available</div>
              )}
            </div>
          </DropdownMenu>

          {/* Policy Filter */}
          <DropdownMenu
            trigger={
              <Button variant="outline" size="sm" className="h-9">
                <Filter className="h-3.5 w-3.5 mr-2" />
                Policy
                {(filters.autoUpdateEnabled !== null || filters.autoRestartEnabled !== null || filters.healthCheckEnabled !== null || filters.selectedDesiredStates.length > 0) && (
                  <span className="ml-1.5 px-1.5 py-0.5 text-xs bg-primary/20 text-primary rounded">
                    {[filters.autoUpdateEnabled, filters.autoRestartEnabled, filters.healthCheckEnabled].filter(v => v !== null).length + filters.selectedDesiredStates.length}
                  </span>
                )}
                <ChevronDown className="h-3.5 w-3.5 ml-2" />
              </Button>
            }
            align="end"
          >
            <div onClick={(e) => e.stopPropagation()} className="min-w-[200px]">
              {/* Auto-update section */}
              <div className="px-2 py-1 text-xs font-medium text-muted-foreground">Auto-update</div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => togglePolicyFilter('auto_update', true)}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.autoUpdateEnabled === true && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Enabled</span>
              </div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => togglePolicyFilter('auto_update', false)}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.autoUpdateEnabled === false && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Disabled</span>
              </div>

              <DropdownMenuSeparator />

              {/* Auto-restart section */}
              <div className="px-2 py-1 text-xs font-medium text-muted-foreground">Auto-restart</div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => togglePolicyFilter('auto_restart', true)}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.autoRestartEnabled === true && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Enabled</span>
              </div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => togglePolicyFilter('auto_restart', false)}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.autoRestartEnabled === false && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Disabled</span>
              </div>

              <DropdownMenuSeparator />

              {/* Health check section */}
              <div className="px-2 py-1 text-xs font-medium text-muted-foreground">HTTP/HTTPS Health Check</div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => togglePolicyFilter('health_check', true)}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.healthCheckEnabled === true && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Enabled</span>
              </div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => togglePolicyFilter('health_check', false)}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.healthCheckEnabled === false && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Disabled</span>
              </div>

              <DropdownMenuSeparator />

              {/* Desired State section */}
              <div className="px-2 py-1 text-xs font-medium text-muted-foreground">Desired State</div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => toggleDesiredStateFilter('should_run')}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.selectedDesiredStates.includes('should_run') && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Should Run</span>
              </div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => toggleDesiredStateFilter('on_demand')}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.selectedDesiredStates.includes('on_demand') && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">On-Demand</span>
              </div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => toggleDesiredStateFilter('unspecified')}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.selectedDesiredStates.includes('unspecified') && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Unspecified</span>
              </div>
            </div>
          </DropdownMenu>

          {/* State Filter */}
          <DropdownMenu
            trigger={
              <Button variant="outline" size="sm" className="h-9">
                <Filter className="h-3.5 w-3.5 mr-2" />
                State
                {(filters.selectedStates.length > 0 || filters.showUpdatesAvailable) && (
                  <span className="ml-1.5 px-1.5 py-0.5 text-xs bg-primary/20 text-primary rounded">
                    {filters.selectedStates.length + (filters.showUpdatesAvailable ? 1 : 0)}
                  </span>
                )}
                <ChevronDown className="h-3.5 w-3.5 ml-2" />
              </Button>
            }
            align="end"
          >
            <div onClick={(e) => e.stopPropagation()}>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => toggleStateFilter('running')}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.selectedStates.includes('running') && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Running</span>
              </div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => toggleStateFilter('stopped')}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.selectedStates.includes('stopped') && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Stopped</span>
              </div>
              <div
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted rounded-sm cursor-pointer"
                onClick={() => {
                  const params = new URLSearchParams(searchParams)
                  if (filters.showUpdatesAvailable) {
                    params.delete('updates')
                  } else {
                    params.set('updates', 'true')
                  }
                  setSearchParams(params, { replace: true })
                }}
              >
                <div className="w-4 h-4 flex items-center justify-center">
                  {filters.showUpdatesAvailable && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="text-xs">Updates available</span>
              </div>
            </div>
          </DropdownMenu>

          {/* Column Customization */}
          <ColumnCustomizationPanel table={table} />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-border">
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
          // Open global modal when expanding from drawer
          if (selectedContainerId) {
            openModal(selectedContainerId, 'info')
          }
        }}
      />

      {/* Bulk Action Bar */}
      <BulkActionBar
        selectedCount={selectedContainerIds.size}
        selectedContainers={data?.filter((c) => selectedContainerIds.has(makeCompositeKey(c))) || []}
        onClearSelection={clearSelection}
        onAction={handleBulkAction}
        onCheckUpdates={handleCheckUpdates}
        onDelete={handleDeleteContainers}
        onUpdateContainers={handleUpdateContainers}
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

      {/* Delete Confirmation Modal */}
      <DeleteConfirmModal
        isOpen={deleteConfirmModalOpen}
        onClose={() => setDeleteConfirmModalOpen(false)}
        onConfirm={handleConfirmDeleteContainers}
        containers={
          data?.filter((c) => selectedContainerIds.has(makeCompositeKey(c))) || []
        }
      />

      {/* Update Confirmation Modal */}
      <UpdateConfirmModal
        isOpen={updateConfirmModalOpen}
        onClose={() => setUpdateConfirmModalOpen(false)}
        onConfirm={handleConfirmUpdateContainers}
        containers={
          data?.filter((c) => selectedContainerIds.has(makeCompositeKey(c))) || []
        }
      />

      {/* Batch Update Validation Confirmation Modal */}
      {validationData && (
        <BatchUpdateValidationConfirmModal
          isOpen={validationModalOpen}
          onClose={() => {
            setValidationModalOpen(false)
            setValidationData(null)
          }}
          onConfirm={handleConfirmValidatedUpdate}
          allowed={validationData.allowed}
          warned={validationData.warned}
          blocked={validationData.blocked}
        />
      )}

      {/* Batch Job Progress Panel */}
      <BatchJobPanel
        jobId={batchJobId}
        isVisible={showJobPanel}
        onClose={() => setShowJobPanel(false)}
        onJobComplete={handleJobComplete}
        bulkActionBarOpen={selectedContainerIds.size > 0}
      />

      {/* Alert Details Drawer */}
      {selectedAlertId && (
        <AlertDetailsDrawer alertId={selectedAlertId} onClose={() => setSelectedAlertId(null)} />
      )}
    </div>
  )
}
