/**
 * Container Table Component - Phase 3b
 *
 * FEATURES:
 * - Sortable, filterable table (TanStack Table)
 * - Real-time status updates
 * - Container actions (start/stop/restart)
 * - Color-coded status badges
 *
 * ARCHITECTURE:
 * - TanStack Table v8 for table logic
 * - TanStack Query for data fetching
 * - Mutation hooks for actions
 */

import { useMemo, useState } from 'react'
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
import type { Container, ContainerAction } from './types'

// Status badge component
function StatusBadge({ state }: { state: Container['state'] }) {
  const colorMap = {
    running: 'bg-success/10 text-success',
    stopped: 'bg-muted text-muted-foreground',
    paused: 'bg-warning/10 text-warning',
    restarting: 'bg-info/10 text-info',
    removing: 'bg-danger/10 text-danger',
    dead: 'bg-danger/10 text-danger',
  }

  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${
        colorMap[state] || 'bg-muted text-muted-foreground'
      }`}
    >
      {state.charAt(0).toUpperCase() + state.slice(1)}
    </span>
  )
}

export function ContainerTable() {
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [globalFilter, setGlobalFilter] = useState('')

  const queryClient = useQueryClient()

  // Fetch containers (backend returns array directly, not wrapped in object)
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
      // Invalidate and refetch containers
      queryClient.invalidateQueries({ queryKey: ['containers'] })

      // Show success toast
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

  // Table columns
  const columns = useMemo<ColumnDef<Container>[]>(
    () => [
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
        cell: ({ row }) => <StatusBadge state={row.original.state} />,
      },
      {
        accessorKey: 'image',
        header: 'Image',
        cell: ({ row }) => (
          <div className="max-w-md truncate text-sm text-muted-foreground">
            {row.original.image}
          </div>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Uptime',
        cell: ({ row }) => (
          <div className="text-sm text-muted-foreground">
            {row.original.status}
          </div>
        ),
      },
      {
        accessorKey: 'host_name',
        header: 'Host',
        cell: ({ row }) => (
          <div className="text-sm">
            {row.original.host_name || 'localhost'}
          </div>
        ),
      },
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
          <thead className="border-b border-border bg-surface-2">
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
                  className="hover:bg-surface-2 transition-colors"
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
