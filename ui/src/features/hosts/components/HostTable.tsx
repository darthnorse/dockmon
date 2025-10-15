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

import { useMemo, useState, useEffect } from 'react'
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
import {
  Circle,
  ArrowUpDown,
  Settings,
  ShieldCheck,
  Shield,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { TagChip } from '@/components/TagChip'
import { useHosts } from '../hooks/useHosts'
import type { Host } from '@/types/api'
import { HostDrawer } from './drawer/HostDrawer'
import { HostDetailsModal } from './HostDetailsModal'
import { HostBulkActionBar } from './HostBulkActionBar'
import { AlertDetailsDrawer } from '@/features/alerts/components/AlertDetailsDrawer'
import { useHostMetrics, useContainerCounts } from '@/lib/stats/StatsProvider'
import { useSimplifiedWorkflow, useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'
import { useHostAlertCounts, type AlertSeverityCounts } from '@/features/alerts/hooks/useAlerts'
import { useQueryClient } from '@tanstack/react-query'
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

// CPU/Memory percentage (no sparkline) - match container page styling
function HostMetricPercentage({ hostId, metric }: { hostId: string; metric: 'cpu' | 'memory' }) {
  const metrics = useHostMetrics(hostId)
  const currentValue = metric === 'cpu' ? metrics?.cpu_percent : metrics?.mem_percent

  if (currentValue === undefined) {
    return <span className="text-xs text-muted-foreground">-</span>
  }

  return (
    <span className="text-xs text-muted-foreground">
      {currentValue.toFixed(1)}%
    </span>
  )
}

// Alert severity counts with color coding and click-to-open-drawer
function AlertSeverityCountsComponent({
  hostId,
  alertCounts,
  onAlertClick
}: {
  hostId: string
  alertCounts: Map<string, AlertSeverityCounts> | undefined
  onAlertClick: (alertId: string) => void
}) {
  const counts = alertCounts?.get(hostId)

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
  const queryClient = useQueryClient()
  const { data: preferences } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const [sorting, setSorting] = useState<SortingState>(preferences?.host_table_sort || [])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [searchParams, setSearchParams] = useSearchParams()
  const { enabled: simplifiedWorkflow } = useSimplifiedWorkflow()

  // Initialize sorting from preferences when loaded
  useEffect(() => {
    if (preferences?.host_table_sort) {
      setSorting(preferences.host_table_sort as SortingState)
    }
  }, [preferences?.host_table_sort])

  // Save sorting changes to preferences
  useEffect(() => {
    // Don't save on initial load (empty array)
    if (sorting.length === 0 && !preferences?.host_table_sort) return

    // Debounce to avoid too many updates
    const timer = setTimeout(() => {
      updatePreferences.mutate({ host_table_sort: sorting })
    }, 500)

    return () => clearTimeout(timer)
  }, [sorting])

  // Fetch alert counts (host-level alerts only)
  const { data: alertCounts } = useHostAlertCounts()

  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null)

  // Modal state
  const [modalOpen, setModalOpen] = useState(false)

  // Handle URL param for opening specific host details modal
  useEffect(() => {
    const hostId = searchParams.get('hostId')
    if (hostId && hosts) {
      const host = hosts.find(h => h.id === hostId)
      if (host) {
        setSelectedHostId(hostId)
        setModalOpen(true)
        // Clear the URL param after opening
        searchParams.delete('hostId')
        setSearchParams(searchParams, { replace: true })
      }
    }
  }, [searchParams, hosts, setSearchParams])

  // Alert drawer state
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null)

  // Selection state for bulk operations
  const [selectedHostIds, setSelectedHostIds] = useState<Set<string>>(new Set())

  const selectedHost = hosts.find(h => h.id === selectedHostId)

  // Selection handlers
  const toggleHostSelection = (hostId: string) => {
    setSelectedHostIds(prev => {
      const newSet = new Set(prev)
      if (newSet.has(hostId)) {
        newSet.delete(hostId)
      } else {
        newSet.add(hostId)
      }
      return newSet
    })
  }

  const toggleSelectAll = (table: Table<Host>) => {
    const currentRows = table.getFilteredRowModel().rows
    const currentIds = currentRows.map((row) => row.original.id)

    // Check if all current rows are selected
    const allCurrentSelected = currentIds.every((id: string) => selectedHostIds.has(id))

    if (allCurrentSelected) {
      // Deselect all current rows
      setSelectedHostIds(prev => {
        const newSet = new Set(prev)
        currentIds.forEach((id) => newSet.delete(id))
        return newSet
      })
    } else {
      // Select all current rows
      setSelectedHostIds(prev => {
        const newSet = new Set(prev)
        currentIds.forEach((id) => newSet.add(id))
        return newSet
      })
    }
  }

  const clearSelection = () => {
    setSelectedHostIds(new Set())
  }

  const columns = useMemo<ColumnDef<Host>[]>(
    () => [
      // Checkbox column
      {
        id: 'select',
        header: ({ table }) => {
          const currentRows = table.getFilteredRowModel().rows
          const currentIds = currentRows.map(row => row.original.id)
          const allCurrentSelected = currentIds.length > 0 && currentIds.every(id => selectedHostIds.has(id))

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
              checked={selectedHostIds.has(row.original.id)}
              onChange={() => toggleHostSelection(row.original.id)}
              onClick={(e) => e.stopPropagation()}
              className="h-4 w-4 rounded border-border text-primary focus:ring-primary cursor-pointer"
            />
          </div>
        ),
        size: 50,
        enableSorting: false,
      },

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
                    if (simplifiedWorkflow) {
                      setModalOpen(true)
                    } else {
                      setDrawerOpen(true)
                    }
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

      // 3. Containers
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

      // 4. Alerts
      {
        accessorKey: 'alerts',
        header: 'Alerts',
        cell: ({ row }) => (
          <AlertSeverityCountsComponent
            hostId={row.original.id}
            alertCounts={alertCounts}
            onAlertClick={setSelectedAlertId}
          />
        ),
      },

      // 5. Uptime
      {
        accessorKey: 'daemon_started_at',
        header: 'Uptime',
        cell: ({ row }) => <Uptime daemonStartedAt={row.original.daemon_started_at} />,
      },

      // 6. CPU%
      {
        accessorKey: 'cpu',
        header: 'CPU%',
        cell: ({ row }) => <HostMetricPercentage hostId={row.original.id} metric="cpu" />,
      },

      // 7. RAM%
      {
        accessorKey: 'memory',
        header: 'RAM%',
        cell: ({ row }) => <HostMetricPercentage hostId={row.original.id} metric="memory" />,
      },

      // 8. OS/Version
      {
        accessorKey: 'os_version',
        header: 'OS / Version',
        cell: ({ row }) => <OSVersion osVersion={row.original.os_version} dockerVersion={row.original.docker_version} />,
      },

      // 9. Actions
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => (
          <div className="flex items-center gap-1">
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
          </div>
        ),
      },
    ],
    [selectedHostIds, toggleHostSelection, toggleSelectAll, onEditHost, alertCounts]
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
    <div className={`rounded-md border ${selectedHostIds.size > 0 ? 'pb-32' : ''}`}>
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

      {/* Host Bulk Action Bar */}
      {selectedHostIds.size > 0 && (
        <HostBulkActionBar
          selectedHostIds={selectedHostIds}
          onClearSelection={clearSelection}
          onTagsUpdated={() => {
            queryClient.invalidateQueries({ queryKey: ['hosts'] })
          }}
        />
      )}

      {/* Alert Details Drawer */}
      {selectedAlertId && (
        <AlertDetailsDrawer alertId={selectedAlertId} onClose={() => setSelectedAlertId(null)} />
      )}
    </div>
  )
}
