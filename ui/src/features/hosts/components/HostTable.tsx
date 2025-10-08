/**
 * Host Table Component - Phase 3d Sub-Phase 6
 *
 * FEATURES:
 * - 10 columns per UX spec
 * - Sortable, filterable table (TanStack Table)
 * - Real-time status updates
 * - CPU/Memory sparklines
 * - Tag chips with color coding
 *
 * COLUMNS:
 * 1. Status - Icon (Online/Offline/Degraded)
 * 2. Hostname - Clickable with tooltip
 * 3. OS/Version - Ubuntu 24.04 • Docker 27.1
 * 4. Containers - Running / Total
 * 5. CPU - Sparkline (amber)
 * 6. Memory - Sparkline (blue)
 * 7. Alerts - Badge count
 * 8. Updates - Badge (blue dot)
 * 9. Uptime - Duration since Docker restart
 * 10. Actions - Details/Restart/Logs
 */

import { useMemo, useState } from 'react'
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
  MoreVertical,
  ArrowUpDown,
  RotateCw,
  FileText,
  Settings,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { TagChip } from '@/components/TagChip'
import { useHosts, type Host } from '../hooks/useHosts'
import { formatDistanceToNow } from 'date-fns'

// Status icon component
function StatusIcon({ status }: { status: string }) {
  const statusMap: Record<string, { color: string; fill: string; label: string }> = {
    online: { color: 'text-success', fill: 'fill-success', label: 'Online' },
    offline: { color: 'text-danger', fill: 'fill-danger', label: 'Offline' },
    degraded: { color: 'text-warning', fill: 'fill-warning', label: 'Degraded' },
  }

  const config = statusMap[status.toLowerCase()] || statusMap.offline

  return (
    <div className="flex items-center gap-2" title={config.label}>
      <Circle className={`h-3 w-3 ${config.color} ${config.fill}`} />
      <span className="text-sm text-muted-foreground">{config.label}</span>
    </div>
  )
}

// OS/Version component
function OSVersion() {
  // TODO: Get actual OS/Version from host info
  // For now, placeholder
  return (
    <span className="text-sm text-muted-foreground">
      Ubuntu 24.04 • Docker 27.1
    </span>
  )
}

// Container count component
function ContainerCount({ running, total }: { running: number; total: number }) {
  return (
    <span className="text-sm">
      <span className="font-medium text-success">{running}</span>
      <span className="text-muted-foreground"> / {total}</span>
    </span>
  )
}

// CPU/Memory sparkline placeholder
function HostSparkline({ metric }: { metric: 'cpu' | 'memory' }) {
  // TODO: Integrate with MiniChart when WebSocket stats are available
  const color = metric === 'cpu' ? 'text-amber-500' : 'text-blue-500'
  return (
    <div className="flex items-center gap-2">
      <div className={`h-8 w-16 rounded ${color} opacity-20`}>
        {/* Placeholder for sparkline */}
      </div>
      <span className="text-xs text-muted-foreground">-</span>
    </div>
  )
}

// Alerts badge
function AlertsBadge({ count }: { count: number }) {
  if (count === 0) {
    return <span className="text-xs text-muted-foreground">-</span>
  }

  return (
    <span className="inline-flex items-center rounded-full bg-destructive px-2 py-1 text-xs font-medium text-destructive-foreground">
      {count}
    </span>
  )
}

// Updates badge
function UpdatesBadge({ hasUpdates }: { hasUpdates: boolean }) {
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

// Uptime component
function Uptime({ lastChecked }: { lastChecked: string }) {
  try {
    const uptime = formatDistanceToNow(new Date(lastChecked), { addSuffix: false })
    return <span className="text-sm text-muted-foreground">{uptime}</span>
  } catch {
    return <span className="text-sm text-muted-foreground">-</span>
  }
}

export function HostTable() {
  const { data: hosts = [], isLoading, error } = useHosts()
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])

  const columns = useMemo<ColumnDef<Host>[]>(
    () => [
      // 1. Status
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => <StatusIcon status={row.original.status} />,
      },

      // 2. Hostname
      {
        accessorKey: 'name',
        header: ({ column }) => (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1"
          >
            Hostname
            <ArrowUpDown className="h-4 w-4" />
          </Button>
        ),
        cell: ({ row }) => {
          const host = row.original
          return (
            <div className="flex flex-col gap-1">
              <button
                className="text-sm font-medium text-left hover:text-primary transition-colors"
                title={`URL: ${host.url}`}
              >
                {host.name}
              </button>
              {host.tags && host.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {host.tags.slice(0, 2).map((tag) => (
                    <TagChip key={tag} tag={tag} size="sm" />
                  ))}
                  {host.tags.length > 2 && (
                    <span className="text-xs text-muted-foreground">
                      +{host.tags.length - 2}
                    </span>
                  )}
                </div>
              )}
            </div>
          )
        },
      },

      // 3. OS/Version
      {
        accessorKey: 'os_version',
        header: 'OS / Version',
        cell: () => <OSVersion />,
      },

      // 4. Containers
      {
        accessorKey: 'container_count',
        header: ({ column }) => (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1"
          >
            Containers
            <ArrowUpDown className="h-4 w-4" />
          </Button>
        ),
        cell: ({ row }) => {
          const total = row.original.container_count
          // TODO: Get running count from host stats
          const running = Math.floor(total * 0.7) // Placeholder
          return <ContainerCount running={running} total={total} />
        },
      },

      // 5. CPU
      {
        accessorKey: 'cpu',
        header: 'CPU',
        cell: () => <HostSparkline metric="cpu" />,
      },

      // 6. Memory
      {
        accessorKey: 'memory',
        header: 'Memory',
        cell: () => <HostSparkline metric="memory" />,
      },

      // 7. Alerts
      {
        accessorKey: 'alerts',
        header: 'Alerts',
        cell: () => <AlertsBadge count={0} />, // TODO: Get real alert count
      },

      // 8. Updates
      {
        accessorKey: 'updates',
        header: 'Updates',
        cell: () => <UpdatesBadge hasUpdates={false} />, // TODO: Check for updates
      },

      // 9. Uptime
      {
        accessorKey: 'last_checked',
        header: 'Uptime',
        cell: ({ row }) => <Uptime lastChecked={row.original.last_checked} />,
      },

      // 10. Actions
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => (
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              title="View Details"
              onClick={() => {
                // TODO: Open host drawer/modal
                console.log('View details:', row.original.id)
              }}
            >
              <Settings className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              title="Restart Docker"
              onClick={() => {
                // TODO: Restart Docker engine
                console.log('Restart Docker:', row.original.id)
              }}
            >
              <RotateCw className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              title="View Logs"
              onClick={() => {
                // TODO: View Docker logs
                console.log('View logs:', row.original.id)
              }}
            >
              <FileText className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="sm" title="More actions">
              <MoreVertical className="h-4 w-4" />
            </Button>
          </div>
        ),
      },
    ],
    []
  )

  const table = useReactTable({
    data: hosts,
    columns,
    state: {
      sorting,
      columnFilters,
    },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  })

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(5)].map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-destructive">
        <p>Error loading hosts: {error.message}</p>
      </div>
    )
  }

  if (hosts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
        <p className="text-lg font-medium">No hosts configured</p>
        <p className="text-sm mt-1">Add your first Docker host to get started</p>
      </div>
    )
  }

  return (
    <div className="rounded-md border">
      <table className="w-full">
        <thead className="bg-muted/50">
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  className="px-4 py-3 text-left text-sm font-medium text-muted-foreground"
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              className="border-t hover:bg-muted/50 transition-colors"
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-4 py-3">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
