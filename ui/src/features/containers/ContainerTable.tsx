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

import { useMemo, useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
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
import {
  Circle,
  PlayCircle,
  Square,
  RotateCw,
  MoreVertical,
  ArrowUpDown,
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
import type { Container, ContainerAction } from './types'

/**
 * Status icon with color coding (Phase 3d UX spec)
 * Uses Circle icon with fill for visual consistency
 */
function StatusIcon({ state }: { state: Container['state'] }) {
  const iconMap = {
    running: { color: 'text-success', fill: 'fill-success', label: 'Running', animate: false },
    stopped: { color: 'text-muted-foreground', fill: 'fill-muted-foreground', label: 'Stopped', animate: false },
    paused: { color: 'text-warning', fill: 'fill-warning', label: 'Paused', animate: false },
    restarting: { color: 'text-info', fill: 'fill-info', label: 'Restarting', animate: true },
    removing: { color: 'text-danger', fill: 'fill-danger', label: 'Removing', animate: false },
    dead: { color: 'text-danger', fill: 'fill-danger', label: 'Dead', animate: false },
  }

  const config = iconMap[state] || iconMap.stopped

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
 * Shows RX/TX rates in kB/s with green text
 */
function NetworkIO({ rx, tx }: { rx?: number; tx?: number }) {
  if (!rx && !tx) {
    return <span className="text-xs text-muted-foreground">-</span>
  }

  const formatRate = (bytes?: number) => {
    if (!bytes) return '0'
    const kb = bytes / 1024
    return kb.toFixed(1)
  }

  return (
    <span className="text-xs text-green-500">
      {formatRate(rx)} ↓ | {formatRate(tx)} ↑
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
          showTooltip
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

export function ContainerTable() {
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [globalFilter, setGlobalFilter] = useState('')

  const queryClient = useQueryClient()

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
      toast.success(`Container ${variables.type}ed successfully`, {
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

  // Table columns (Phase 3d UX spec order)
  const columns = useMemo<ColumnDef<Container>[]>(
    () => [
      // 1. Status (icon)
      {
        accessorKey: 'state',
        header: ({ column }) => (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="h-8 px-2 hover:bg-surface-2"
          >
            Status
            <ArrowUpDown className="ml-2 h-4 w-4" />
          </Button>
        ),
        cell: ({ row }) => <StatusIcon state={row.original.state} />,
      },
      // 2. Name (clickable)
      {
        accessorKey: 'name',
        header: ({ column }) => (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="h-8 px-2 hover:bg-surface-2"
          >
            Name
            <ArrowUpDown className="ml-2 h-4 w-4" />
          </Button>
        ),
        cell: ({ row }) => (
          <div className="font-medium">{row.original.name || 'Unknown'}</div>
        ),
      },
      // 3. Image:Tag (tooltip)
      {
        accessorKey: 'image',
        header: 'Image:Tag',
        cell: ({ row }) => <ImageTag image={row.original.image} />,
      },
      // 4. Host (chip with tags)
      {
        accessorKey: 'host_name',
        header: 'Host',
        cell: ({ row }) => {
          const container = row.original
          return (
            <div className="flex flex-col gap-1">
              <div className="text-sm">{container.host_name || 'localhost'}</div>
              {container.tags && container.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {container.tags.slice(0, 2).map((tag) => (
                    <TagChip key={tag} tag={tag} size="sm" />
                  ))}
                  {container.tags.length > 2 && (
                    <span className="text-xs text-muted-foreground">
                      +{container.tags.length - 2}
                    </span>
                  )}
                </div>
              )}
            </div>
          )
        },
      },
      // 5. Uptime (duration)
      {
        accessorKey: 'status',
        header: 'Uptime',
        cell: ({ row }) => (
          <div className="text-sm text-muted-foreground">
            {row.original.status}
          </div>
        ),
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
          // If we have real-time stats, show sparkline
          if (container.memory_percent !== undefined) {
            const usage = container.memory_usage ? (container.memory_usage / (1024 * 1024)).toFixed(0) : '-'
            const limit = container.memory_limit ? (container.memory_limit / (1024 * 1024)).toFixed(0) : '-'

            return (
              <div title={`${usage} MB / ${limit} MB`}>
                <ContainerSparkline
                  containerId={container.id}
                  metric="memory"
                  color="memory"
                  currentValue={container.memory_percent}
                />
              </div>
            )
          }
          // Fallback: show dash
          return <span className="text-xs text-muted-foreground">-</span>
        },
      },
      // 8. Network I/O (optional)
      {
        id: 'network',
        header: 'Network',
        cell: ({ row }) => (
          <NetworkIO rx={row.original.network_rx} tx={row.original.network_tx} />
        ),
      },
      // 9. Actions (Start/Stop/Restart/More)
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => {
          const container = row.original
          const isRunning = container.state === 'running'
          const isStopped = container.state === 'stopped'

          return (
            <div className="flex items-center gap-2">
              {isStopped && (
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
                  disabled={actionMutation.isPending || !container.host_id}
                  title="Start container"
                >
                  <PlayCircle className="h-4 w-4 text-success" />
                </Button>
              )}

              {isRunning && (
                <>
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
                    disabled={actionMutation.isPending || !container.host_id}
                    title="Stop container"
                  >
                    <Square className="h-4 w-4 text-danger" />
                  </Button>

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
                    disabled={actionMutation.isPending || !container.host_id}
                    title="Restart container"
                  >
                    <RotateCw className="h-4 w-4 text-info" />
                  </Button>
                </>
              )}

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
    [actionMutation]
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
      <div className="overflow-hidden rounded-lg border border-border bg-surface-1">
        <table className="w-full">
          <thead className="border-b border-border bg-surface-2 sticky top-0">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-4 py-3 text-left text-sm font-medium"
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
                  className="hover:bg-[#151827] transition-colors"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3">
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
    </div>
  )
}
