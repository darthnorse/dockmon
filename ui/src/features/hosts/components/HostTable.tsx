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
  ShieldCheck,
  Shield,
  Eye,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { TagChip } from '@/components/TagChip'
import { useHosts, type Host } from '../hooks/useHosts'
import { HostDrawer } from './drawer/HostDrawer'
import { HostDetailsModal } from './HostDetailsModal'
import { useHostMetrics, useHostSparklines, useContainerCounts } from '@/lib/stats/StatsProvider'
import { MiniChart } from '@/lib/charts/MiniChart'
import { debug } from '@/lib/debug'

// Status icon component
function StatusIcon({ status }: { status: string }) {
  const statusMap: Record<string, { color: string; fill: string; label: string }> = {
    online: { color: 'text-success', fill: 'fill-success', label: 'Online' },
    offline: { color: 'text-danger', fill: 'fill-danger', label: 'Offline' },
    degraded: { color: 'text-warning', fill: 'fill-warning', label: 'Degraded' },
  }

  const config = statusMap[status?.toLowerCase()] || statusMap.offline

  if (!config) {
    return <span className="text-sm text-muted-foreground">Unknown</span>
  }

  return (
    <div className="flex items-center gap-2" title={config.label}>
      <Circle className={`h-3 w-3 ${config.color} ${config.fill}`} />
      <span className="text-sm text-muted-foreground">{config.label}</span>
    </div>
  )
}

// Security indicator component for TLS/Channel status
function SecurityIndicator({ url, securityStatus }: { url: string; securityStatus?: string | null | undefined }) {
  // Determine connection type and security
  const isUnixSocket = url.startsWith('unix://')
  const isTcp = url.startsWith('tcp://')

  // For UNIX sockets - always secure (local)
  if (isUnixSocket) {
    return (
      <div title="Local UNIX socket (TLS not applicable)">
        <Shield className="h-4 w-4 text-muted-foreground opacity-70" />
      </div>
    )
  }

  // For TCP connections - check security_status
  if (isTcp) {
    // Backend uses 'secure' for mTLS (we only support mTLS, not plain TLS)
    const isSecure = securityStatus === 'secure' || securityStatus === 'tls' || securityStatus === 'mtls'

    if (isSecure) {
      return (
        <div title="Secure (mTLS)">
          <ShieldCheck className="h-4 w-4 text-[--accent] opacity-80" />
        </div>
      )
    } else {
      return (
        <div title="Insecure connection (no mTLS)">
          <Shield className="h-4 w-4 text-muted-foreground opacity-70 ring-1 ring-dashed ring-border rounded-sm" />
        </div>
      )
    }
  }

  // Default - no indicator
  return null
}

// OS/Version component
function OSVersion({ osVersion, dockerVersion }: { osVersion?: string | null | undefined; dockerVersion?: string | null | undefined }) {
  if (!osVersion && !dockerVersion) {
    return <span className="text-sm text-muted-foreground">-</span>
  }

  const parts = []
  if (osVersion) parts.push(osVersion)
  if (dockerVersion) parts.push(`Docker ${dockerVersion}`)

  return <span className="text-sm text-muted-foreground">{parts.join(' • ')}</span>
}

// Container count component with real-time data
function ContainerCount({ hostId }: { hostId: string }) {
  const counts = useContainerCounts(hostId)

  return (
    <span className="text-sm">
      <span className="font-medium text-success">{counts.running}</span>
      <span className="text-muted-foreground"> / {counts.total}</span>
    </span>
  )
}

// CPU/Memory sparkline with real-time data
function HostSparkline({ hostId, metric }: { hostId: string; metric: 'cpu' | 'memory' }) {
  const metrics = useHostMetrics(hostId)
  const sparklines = useHostSparklines(hostId)

  // Show placeholder if no data yet
  if (!sparklines) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-8 w-16 rounded bg-muted-foreground/10" />
        <span className="text-xs text-muted-foreground">-</span>
      </div>
    )
  }

  const data = metric === 'cpu' ? sparklines.cpu : sparklines.mem
  const currentValue = metric === 'cpu' ? metrics?.cpu_percent : metrics?.mem_percent
  const color = metric === 'cpu' ? 'cpu' : 'memory'

  return (
    <div className="flex items-center gap-2">
      <MiniChart
        data={data}
        color={color}
        width={60}
        height={24}
        label={`${metric.toUpperCase()} usage`}
      />
      {currentValue !== undefined && (
        <span className="text-xs text-muted-foreground font-mono w-12 text-right">
          {currentValue.toFixed(1)}%
        </span>
      )}
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

// Uptime component - Shows time since Docker daemon started
function Uptime({ daemonStartedAt }: { daemonStartedAt?: string | null | undefined }) {
  if (!daemonStartedAt) {
    return <span className="text-sm text-muted-foreground">-</span>
  }

  try {
    const startTime = new Date(daemonStartedAt)
    const now = new Date()
    const diffMs = now.getTime() - startTime.getTime()

    const days = Math.floor(diffMs / (1000 * 60 * 60 * 24))
    const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))

    let uptimeStr = ''
    if (days > 0) {
      uptimeStr = `${days}d ${hours}h`
    } else if (hours > 0) {
      uptimeStr = `${hours}h ${minutes}m`
    } else {
      uptimeStr = `${minutes}m`
    }

    return <span className="text-sm text-muted-foreground">{uptimeStr}</span>
  } catch {
    return <span className="text-sm text-muted-foreground">-</span>
  }
}

interface HostTableProps {
  onEditHost?: (host: Host) => void
}

export function HostTable({ onEditHost }: HostTableProps = {}) {
  const { data: hosts = [], isLoading, error } = useHosts()
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])

  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null)

  // Modal state
  const [modalOpen, setModalOpen] = useState(false)

  const selectedHost = hosts.find(h => h.id === selectedHostId)

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
        header: ({ column }) => {
          const sortDirection = column.getIsSorted()
          return (
            <Button
              variant="ghost"
              onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
              className="flex items-center gap-1"
            >
              Hostname
              <ArrowUpDown className={`h-4 w-4 ${sortDirection ? 'text-primary' : 'text-muted-foreground'}`} />
            </Button>
          )
        },
        cell: ({ row }) => {
          const host = row.original
          return (
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <button
                  className="text-sm font-medium text-left hover:text-primary transition-colors cursor-pointer"
                  title={`URL: ${host.url}`}
                  onClick={() => {
                    setSelectedHostId(row.original.id)
                    setDrawerOpen(true)
                  }}
                >
                  {host.name}
                </button>
                <SecurityIndicator url={host.url} securityStatus={host.security_status} />
              </div>
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
        cell: ({ row }) => <OSVersion osVersion={row.original.os_version} dockerVersion={row.original.docker_version} />,
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
        cell: ({ row }) => <ContainerCount hostId={row.original.id} />,
      },

      // 5. CPU
      {
        accessorKey: 'cpu',
        header: 'CPU',
        cell: ({ row }) => <HostSparkline hostId={row.original.id} metric="cpu" />,
      },

      // 6. Memory
      {
        accessorKey: 'memory',
        header: 'Memory',
        cell: ({ row }) => <HostSparkline hostId={row.original.id} metric="memory" />,
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
        accessorKey: 'daemon_started_at',
        header: 'Uptime',
        cell: ({ row }) => <Uptime daemonStartedAt={row.original.daemon_started_at} />,
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
                setSelectedHostId(row.original.id)
                setDrawerOpen(true)
              }}
            >
              <Eye className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              title="Edit Host"
              onClick={() => {
                onEditHost?.(row.original)
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
                debug.log('HostTable', 'Restart Docker:', row.original.id)
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
                debug.log('HostTable', 'View logs:', row.original.id)
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
    [onEditHost]
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
        <thead className="bg-muted/50 sticky top-0 z-10">
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
              className="border-t hover:bg-[#151827] transition-colors"
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

      {/* Host Drawer */}
      <HostDrawer
        hostId={selectedHostId}
        host={selectedHost}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false)
          setSelectedHostId(null)
        }}
        onEdit={(hostId) => {
          const host = hosts.find(h => h.id === hostId)
          if (host) {
            onEditHost?.(host)
          }
          setDrawerOpen(false)
        }}
        onDelete={(hostId) => {
          // TODO: Implement delete dialog
          debug.log('HostTable', 'Delete host:', hostId)
        }}
        onExpand={() => {
          setDrawerOpen(false)
          setModalOpen(true)
        }}
      />

      {/* Host Details Modal */}
      <HostDetailsModal
        hostId={selectedHostId}
        host={selectedHost}
        open={modalOpen}
        onClose={() => {
          setModalOpen(false)
        }}
      />
    </div>
  )
}
