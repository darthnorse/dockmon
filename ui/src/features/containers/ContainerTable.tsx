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

import { useMemo, useState, useRef, useEffect } from 'react'
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
} from 'lucide-react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import { POLLING_CONFIG } from '@/lib/config/polling'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { TagChip } from '@/components/TagChip'
import { MiniChart } from '@/lib/charts/MiniChart'
import { useStatsHistory } from '@/lib/hooks/useStatsHistory'
import { ContainerDrawer } from './components/ContainerDrawer'
import { BulkActionBar } from './components/BulkActionBar'
import { BulkActionConfirmModal } from './components/BulkActionConfirmModal'
import { BatchJobPanel } from './components/BatchJobPanel'
import type { Container, ContainerAction } from './types'

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
 * Image:Tag display with tooltip (Phase 3d UX spec)
 * Shows short version, tooltip reveals full image string
 */
function ImageTag({ image }: { image: string }) {
  // Extract image:tag from full string
  const parseImage = (fullImage: string) => {
    // Remove registry prefix if present (e.g., docker.io/library/)
    const parts = fullImage.split('/')
    const imageTag = parts[parts.length - 1] || fullImage

    // Split by @ to remove digest if present
    const withoutDigest = imageTag.split('@')[0]

    return withoutDigest || fullImage
  }

  const shortImage = parseImage(image)

  return (
    <div className="max-w-md truncate text-sm text-muted-foreground" title={image}>
      {shortImage}
    </div>
  )
}

/**
 * Network I/O display (Phase 3d UX spec)
 * Shows real-time network rate (RX+TX) in KB/s or MB/s with green text
 * Rate is calculated by the backend stats service
 */
function NetworkIO({ rate }: { rate?: number }) {
  if (rate === undefined || rate === null) {
    return <span className="text-xs text-muted-foreground">-</span>
  }

  const formatRate = (bytesPerSec: number) => {
    if (bytesPerSec < 1024) return `${bytesPerSec.toFixed(0)} B/s`
    const kb = bytesPerSec / 1024
    if (kb < 1024) return `${kb.toFixed(1)} KB/s`
    const mb = kb / 1024
    return `${mb.toFixed(1)} MB/s`
  }

  return (
    <span className="text-xs text-green-500">
      {formatRate(rate)}
    </span>
  )
}

/**
 * Container sparkline with stats history
 * Uses adaptive polling for bandwidth optimization
 */
function ContainerSparkline({
  containerId,
  metric,
  color,
  currentValue
}: {
  containerId: string
  metric: 'cpu' | 'memory'
  color: 'cpu' | 'memory'
  currentValue?: number
}) {
  const rowRef = useRef<HTMLDivElement>(null)
  const { getHistory } = useStatsHistory(containerId)

  // TODO: Hook up WebSocket listener for stats
  // For now, show current value if available

  const history = getHistory(metric)
  const latest = currentValue ?? (history.length > 0 ? history[history.length - 1] : null)

  return (
    <div ref={rowRef} className="flex items-center gap-2">
      {history.length > 0 && (
        <MiniChart
          data={history}
          color={color}
          height={40}
          width={80}
          label={`${metric} usage`}
        />
      )}
      {latest !== null && latest !== undefined && (
        <span className="text-xs text-muted-foreground">
          {latest.toFixed(1)}%
        </span>
      )}
    </div>
  )
}

interface ContainerTableProps {
  hostId?: string // Optional: filter by specific host
}

export function ContainerTable({ hostId: propHostId }: ContainerTableProps = {}) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [globalFilter, setGlobalFilter] = useState('')
  const [searchParams] = useSearchParams()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedContainerId, setSelectedContainerId] = useState<string | null>(null)
  const [selectedContainerIds, setSelectedContainerIds] = useState<Set<string>>(new Set())
  const [confirmModalOpen, setConfirmModalOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<'start' | 'stop' | 'restart' | null>(null)
  const [batchJobId, setBatchJobId] = useState<string | null>(null)
  const [expandedTagsContainerId, setExpandedTagsContainerId] = useState<string | null>(null)

  const queryClient = useQueryClient()

  // Selection handlers
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

  const toggleSelectAll = (table: any) => {
    const currentRows = table.getFilteredRowModel().rows
    const currentIds = currentRows.map((row: any) => row.original.id)

    // Check if all current rows are selected
    const allCurrentSelected = currentIds.every((id: string) => selectedContainerIds.has(id))

    if (allCurrentSelected) {
      // Deselect all current rows
      setSelectedContainerIds(prev => {
        const newSet = new Set(prev)
        currentIds.forEach((id: string) => newSet.delete(id))
        return newSet
      })
    } else {
      // Select all current rows
      setSelectedContainerIds(prev => {
        const newSet = new Set(prev)
        currentIds.forEach((id: string) => newSet.add(id))
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

    const selectedContainers = data.filter((c) => selectedContainerIds.has(c.id))
    const action = mode === 'add' ? 'add-tags' : 'remove-tags'

    try {
      // Create batch job for tag update
      const response = await fetch('/api/batch', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          scope: 'container',
          action,
          ids: Array.from(selectedContainerIds),
          params: { tags },
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to create batch job')
      }

      const result = await response.json()
      setBatchJobId(result.job_id)

      // Show success toast
      const modeText = mode === 'add' ? 'Adding' : 'Removing'
      toast.success(`${modeText} ${tags.length} tag${tags.length !== 1 ? 's' : ''} ${mode === 'remove' ? 'from' : 'to'} ${selectedContainers.length} container${selectedContainers.length !== 1 ? 's' : ''}...`)
    } catch (error) {
      toast.error(`Failed to update tags: ${error instanceof Error ? error.message : 'Unknown error'}`)
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
          const currentIds = currentRows.map(row => row.original.id)
          const allCurrentSelected = currentIds.length > 0 && currentIds.every(id => selectedContainerIds.has(id))

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
              checked={selectedContainerIds.has(row.original.id)}
              onChange={() => toggleContainerSelection(row.original.id)}
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
                  setSelectedContainerId(row.original.id)
                  setDrawerOpen(true)
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
      // 3. Image:Tag (tooltip)
      {
        accessorKey: 'image',
        header: 'Image:Tag',
        cell: ({ row }) => <ImageTag image={row.original.image} />,
      },
      // 4. Host
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
      // 5. Uptime (duration)
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
      // 6. CPU (sparkline)
      {
        id: 'cpu',
        header: 'CPU',
        cell: ({ row }) => {
          const container = row.original
          // If we have real-time stats, show sparkline
          if (container.cpu_percent !== undefined) {
            return (
              <ContainerSparkline
                containerId={container.id}
                metric="cpu"
                color="cpu"
                currentValue={container.cpu_percent}
              />
            )
          }
          // Fallback: show dash
          return <span className="text-xs text-muted-foreground">-</span>
        },
      },
      // 7. Memory (sparkline/bar)
      {
        id: 'memory',
        header: 'Memory',
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
      // 8. Network I/O (optional)
      {
        id: 'network',
        header: 'Network',
        cell: ({ row }) => {
          const { net_bytes_per_sec } = row.original
          if (net_bytes_per_sec !== null && net_bytes_per_sec !== undefined) {
            return <NetworkIO rate={net_bytes_per_sec} />
          }
          return <NetworkIO />
        },
      },
      // 9. Actions (Start/Stop/Restart/Logs/View details)
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

              {/* Logs button - always enabled */}
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  // TODO: Open logs modal/drawer
                  toast.info('Logs', {
                    description: `View logs for ${container.name}`,
                  })
                }}
                title="View logs"
              >
                <FileText className="h-4 w-4" />
              </Button>

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
    [actionMutation, selectedContainerIds, data, toggleContainerSelection, toggleSelectAll]
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
    <div className="space-y-4">
      {/* Search */}
      <div className="flex items-center gap-4">
        <Input
          placeholder="Search containers..."
          value={globalFilter ?? ''}
          onChange={(e) => setGlobalFilter(e.target.value)}
          className="max-w-sm"
        />
        <div className="text-sm text-muted-foreground">
          {table.getFilteredRowModel().rows.length} container(s)
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full">
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
      />

      {/* Bulk Action Bar */}
      <BulkActionBar
        selectedCount={selectedContainerIds.size}
        selectedContainers={data?.filter((c) => selectedContainerIds.has(c.id)) || []}
        onClearSelection={clearSelection}
        onAction={handleBulkAction}
        onTagUpdate={handleBulkTagUpdate}
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
          data?.filter((c) => selectedContainerIds.has(c.id)) || []
        }
      />

      {/* Batch Job Progress Panel */}
      <BatchJobPanel
        jobId={batchJobId}
        onClose={() => setBatchJobId(null)}
      />
    </div>
  )
}
