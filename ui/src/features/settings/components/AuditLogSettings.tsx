/**
 * Audit Log Settings Component
 * Admin-only audit log viewer with filtering, export, and retention settings
 *
 * Phase 6 of Multi-User Support (v2.3.0)
 */

import { useState, useMemo, useCallback } from 'react'
import {
  Search,
  Download,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Filter,
  Settings,
  Calendar,
  User as UserIcon,
  Activity,
  FileText,
  Clock,
  Trash2,
  AlertTriangle,
  X,
} from 'lucide-react'
import {
  useAuditLog,
  useAuditActions,
  useAuditEntityTypes,
  useAuditUsers,
  useAuditRetention,
  useUpdateAuditRetention,
  useCleanupAuditLog,
  useExportAuditLog,
} from '@/hooks/useAuditLog'
import type { AuditLogQueryParams, AuditLogEntry } from '@/types/audit'
import { ACTION_LABELS, ENTITY_TYPE_LABELS, RETENTION_LABELS } from '@/types/audit'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatDateTime } from '@/lib/utils/timeFormat'

// =============================================================================
// Constants
// =============================================================================

const PAGE_SIZE = 25

// Shared CSS classes
const INPUT_CLASS =
  'w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none'

// Action color mappings
const ACTION_COLORS: Record<string, string> = {
  delete: 'text-red-400',
  login_failed: 'text-red-400',
  create: 'text-green-400',
  login: 'text-green-400',
  update: 'text-blue-400',
  deploy: 'text-blue-400',
  shell: 'text-yellow-400',
}

// =============================================================================
// Subcomponents
// =============================================================================

function StatCard({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-3">
      <div className="text-xs text-gray-400">{label}</div>
      <div className="mt-1 text-lg font-semibold text-white">{value}</div>
    </div>
  )
}

function AuditEntryRow({
  entry,
  isExpanded,
  onToggle,
}: {
  entry: AuditLogEntry
  isExpanded: boolean
  onToggle: () => void
}) {
  const actionLabel = ACTION_LABELS[entry.action] || entry.action
  const entityTypeLabel = ENTITY_TYPE_LABELS[entry.entity_type] || entry.entity_type

  // Get action color from mapping, with fallbacks for partial matches
  const actionColor = useMemo(() => {
    // Direct match first
    if (ACTION_COLORS[entry.action]) {
      return ACTION_COLORS[entry.action]
    }
    // Partial matches for composite actions
    if (entry.action.includes('delete')) return 'text-red-400'
    if (entry.action.includes('create')) return 'text-green-400'
    if (entry.action.includes('update')) return 'text-blue-400'
    return 'text-gray-400'
  }, [entry.action])

  return (
    <>
      <tr onClick={onToggle} className="cursor-pointer transition-colors hover:bg-gray-800/50">
        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-300">
          {formatDateTime(entry.created_at)}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-white">
          {entry.username}
        </td>
        <td className={`whitespace-nowrap px-4 py-3 text-sm font-medium ${actionColor}`}>
          {actionLabel}
        </td>
        <td className="px-4 py-3 text-sm text-gray-300">
          <div className="flex items-center gap-2">
            <span className="rounded bg-gray-700 px-1.5 py-0.5 text-xs text-gray-300">
              {entityTypeLabel}
            </span>
            {entry.entity_name && <span className="truncate text-white">{entry.entity_name}</span>}
          </div>
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-400">
          {entry.ip_address || '-'}
        </td>
      </tr>

      {isExpanded && (
        <tr className="bg-gray-800/30">
          <td colSpan={5} className="px-4 py-3">
            <div className="space-y-2 text-sm">
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {entry.entity_id && (
                  <div>
                    <span className="text-gray-400">Entity ID:</span>{' '}
                    <span className="font-mono text-white">{entry.entity_id}</span>
                  </div>
                )}
                {entry.host_id && (
                  <div>
                    <span className="text-gray-400">Host ID:</span>{' '}
                    <span className="font-mono text-white">{entry.host_id}</span>
                  </div>
                )}
                {entry.user_agent && (
                  <div className="col-span-2">
                    <span className="text-gray-400">User Agent:</span>{' '}
                    <span className="text-gray-300">{entry.user_agent}</span>
                  </div>
                )}
              </div>

              {entry.details && Object.keys(entry.details).length > 0 && (
                <div>
                  <span className="text-gray-400">Details:</span>
                  <pre className="mt-1 overflow-x-auto rounded bg-gray-900 p-2 text-xs text-gray-300">
                    {JSON.stringify(entry.details, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function RetentionDialog({
  isOpen,
  onClose,
  retention,
  onRetentionChange,
  onCleanup,
  isPending,
}: {
  isOpen: boolean
  onClose: () => void
  retention: { retention_days: number; valid_options: number[] } | undefined
  onRetentionChange: (days: number) => void
  onCleanup: () => void
  isPending: boolean
}) {
  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Audit Log Retention</DialogTitle>
          <DialogDescription>
            Configure how long audit entries are retained before automatic cleanup.
          </DialogDescription>
        </DialogHeader>

        <div className="my-4 space-y-4">
          <div className="text-sm text-gray-400">
            Current setting:{' '}
            <span className="font-medium text-white">
              {retention?.retention_days === 0 ? 'Unlimited' : `${retention?.retention_days} days`}
            </span>
          </div>

          <div className="space-y-2">
            {retention?.valid_options.map((days) => (
              <button
                key={days}
                onClick={() => onRetentionChange(days)}
                disabled={isPending}
                className={`w-full rounded-lg border p-3 text-left transition-colors ${
                  retention?.retention_days === days
                    ? 'border-blue-500 bg-blue-900/20'
                    : 'border-gray-700 bg-gray-800 hover:border-gray-600'
                }`}
              >
                <div className="font-medium text-white">
                  {RETENTION_LABELS[days] || `${days} days`}
                </div>
                {days === 0 && (
                  <div className="mt-1 text-xs text-gray-400">
                    Entries will never be automatically deleted
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button variant="destructive" onClick={onCleanup}>
            <Trash2 className="mr-2 h-4 w-4" />
            Manual Cleanup
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CleanupDialog({
  isOpen,
  onClose,
  retentionDays,
  onConfirm,
  isPending,
}: {
  isOpen: boolean
  onClose: () => void
  retentionDays: number
  onConfirm: () => void
  isPending: boolean
}) {
  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-900/20">
              <AlertTriangle className="h-5 w-5 text-red-400" />
            </div>
            <div>
              <DialogTitle>Manual Cleanup</DialogTitle>
              <DialogDescription>
                Delete audit entries older than the retention period.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="my-4">
          <p className="text-sm text-gray-400">
            This will permanently delete all audit entries older than{' '}
            <span className="font-medium text-white">
              {retentionDays === 0
                ? '(retention is unlimited, no entries will be deleted)'
                : `${retentionDays} days`}
            </span>
            .
          </p>
          {retentionDays !== 0 && (
            <p className="mt-2 text-sm text-yellow-400">This action cannot be undone.</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={isPending || retentionDays === 0}
          >
            {isPending ? 'Cleaning up...' : 'Delete Old Entries'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// =============================================================================
// Main Component
// =============================================================================

export function AuditLogSettings() {
  // State
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<AuditLogQueryParams>({})
  const [searchInput, setSearchInput] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [showRetentionDialog, setShowRetentionDialog] = useState(false)
  const [showCleanupDialog, setShowCleanupDialog] = useState(false)
  const [expandedEntryId, setExpandedEntryId] = useState<number | null>(null)

  // Queries
  const queryParams = useMemo(() => ({ ...filters, page, page_size: PAGE_SIZE }), [filters, page])
  const { data: auditLog, isLoading, refetch } = useAuditLog(queryParams)
  const { data: actions } = useAuditActions()
  const { data: entityTypes } = useAuditEntityTypes()
  const { data: users } = useAuditUsers()
  const { data: retention } = useAuditRetention()
  const updateRetention = useUpdateAuditRetention()
  const cleanupAuditLog = useCleanupAuditLog()
  const exportAuditLog = useExportAuditLog()

  // Count active filters
  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((v) => v !== undefined && v !== '').length,
    [filters]
  )

  // Handlers
  const handleSearch = useCallback(() => {
    setFilters((prev) => {
      const newFilters = { ...prev }
      if (searchInput) {
        newFilters.search = searchInput
      } else {
        delete newFilters.search
      }
      return newFilters
    })
    setPage(1)
  }, [searchInput])

  const handleFilterChange = useCallback(
    (key: keyof AuditLogQueryParams, value: string | number | undefined) => {
      setFilters((prev) => {
        const newFilters = { ...prev }
        if (value !== undefined && value !== '') {
          // @ts-expect-error - key is valid for the type
          newFilters[key] = value
        } else {
          delete newFilters[key]
        }
        return newFilters
      })
      setPage(1)
    },
    []
  )

  const clearFilters = useCallback(() => {
    setFilters({})
    setSearchInput('')
    setPage(1)
  }, [])

  const handleRetentionChange = useCallback(
    (days: number) => {
      updateRetention.mutate({ retention_days: days })
      setShowRetentionDialog(false)
    },
    [updateRetention]
  )

  const handleCleanup = useCallback(() => {
    cleanupAuditLog.mutate()
    setShowCleanupDialog(false)
  }, [cleanupAuditLog])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">Audit Log</h2>
          <p className="mt-1 text-sm text-gray-400">View and export security audit events</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowRetentionDialog(true)}
            className="flex items-center gap-1"
          >
            <Settings className="h-4 w-4" />
            Retention
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => exportAuditLog.mutate(filters)}
            disabled={exportAuditLog.isPending}
            className="flex items-center gap-1"
          >
            <Download className="h-4 w-4" />
            {exportAuditLog.isPending ? 'Exporting...' : 'Export CSV'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            className="flex items-center gap-1"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Stats Summary */}
      {retention && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Total Entries" value={retention.total_entries.toLocaleString()} />
          <StatCard
            label="Retention"
            value={retention.retention_days === 0 ? 'Unlimited' : `${retention.retention_days} days`}
          />
          <StatCard
            label="Oldest Entry"
            value={
              <span className="text-sm">
                {retention.oldest_entry_date ? formatDateTime(retention.oldest_entry_date) : 'N/A'}
              </span>
            }
          />
          <StatCard label="Filtered Results" value={auditLog?.total.toLocaleString() ?? '-'} />
        </div>
      )}

      {/* Search and Filters */}
      <div className="space-y-4">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Search username, entity name, or entity ID..."
              className={`${INPUT_CLASS} pl-10`}
            />
          </div>
          <Button onClick={handleSearch} variant="default" size="sm">
            Search
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowFilters(!showFilters)}
            className={`flex items-center gap-1 ${activeFilterCount > 0 ? 'border-blue-500 text-blue-400' : ''}`}
          >
            <Filter className="h-4 w-4" />
            Filters
            {activeFilterCount > 0 && (
              <span className="ml-1 rounded-full bg-blue-500 px-1.5 py-0.5 text-xs text-white">
                {activeFilterCount}
              </span>
            )}
          </Button>
        </div>

        {/* Expandable Filters */}
        {showFilters && (
          <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-4">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400">
                  <UserIcon className="mr-1 inline-block h-3 w-3" />
                  User
                </label>
                <select
                  value={filters.user_id ?? ''}
                  onChange={(e) =>
                    handleFilterChange('user_id', e.target.value ? Number(e.target.value) : undefined)
                  }
                  className={INPUT_CLASS}
                >
                  <option value="">All users</option>
                  {users?.map((user) => (
                    <option key={user.user_id} value={user.user_id}>
                      {user.username}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400">
                  <Activity className="mr-1 inline-block h-3 w-3" />
                  Action
                </label>
                <select
                  value={filters.action ?? ''}
                  onChange={(e) => handleFilterChange('action', e.target.value || undefined)}
                  className={INPUT_CLASS}
                >
                  <option value="">All actions</option>
                  {actions?.map((action) => (
                    <option key={action} value={action}>
                      {ACTION_LABELS[action] || action}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400">
                  <FileText className="mr-1 inline-block h-3 w-3" />
                  Entity Type
                </label>
                <select
                  value={filters.entity_type ?? ''}
                  onChange={(e) => handleFilterChange('entity_type', e.target.value || undefined)}
                  className={INPUT_CLASS}
                >
                  <option value="">All types</option>
                  {entityTypes?.map((type) => (
                    <option key={type} value={type}>
                      {ENTITY_TYPE_LABELS[type] || type}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400">
                  <Calendar className="mr-1 inline-block h-3 w-3" />
                  Start Date
                </label>
                <input
                  type="date"
                  value={filters.start_date?.split('T')[0] ?? ''}
                  onChange={(e) =>
                    handleFilterChange(
                      'start_date',
                      e.target.value ? `${e.target.value}T00:00:00Z` : undefined
                    )
                  }
                  className={INPUT_CLASS}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-gray-400">
                  <Calendar className="mr-1 inline-block h-3 w-3" />
                  End Date
                </label>
                <input
                  type="date"
                  value={filters.end_date?.split('T')[0] ?? ''}
                  onChange={(e) =>
                    handleFilterChange(
                      'end_date',
                      e.target.value ? `${e.target.value}T23:59:59Z` : undefined
                    )
                  }
                  className={INPUT_CLASS}
                />
              </div>
            </div>

            {activeFilterCount > 0 && (
              <div className="mt-4 flex justify-end">
                <Button variant="ghost" size="sm" onClick={clearFilters}>
                  <X className="mr-1 h-4 w-4" />
                  Clear Filters
                </Button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Audit Log Table */}
      {isLoading ? (
        <div className="py-8 text-center text-gray-400">Loading audit log...</div>
      ) : !auditLog?.entries.length ? (
        <div className="rounded-lg border border-gray-800 bg-gray-900/30 p-8 text-center">
          <FileText className="mx-auto mb-3 h-12 w-12 text-gray-600" />
          <h3 className="font-medium text-gray-400">No audit entries found</h3>
          <p className="mt-1 text-sm text-gray-500">
            {activeFilterCount > 0
              ? 'Try adjusting your filters'
              : 'Audit entries will appear here as actions occur'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="min-w-full divide-y divide-gray-800">
            <thead className="bg-gray-900/70">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400">
                  <Clock className="mr-1 inline-block h-3 w-3" />
                  Time
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400">
                  <UserIcon className="mr-1 inline-block h-3 w-3" />
                  User
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400">
                  <Activity className="mr-1 inline-block h-3 w-3" />
                  Action
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400">
                  <FileText className="mr-1 inline-block h-3 w-3" />
                  Entity
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400">
                  IP Address
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800 bg-gray-900/30">
              {auditLog.entries.map((entry) => (
                <AuditEntryRow
                  key={entry.id}
                  entry={entry}
                  isExpanded={expandedEntryId === entry.id}
                  onToggle={() => setExpandedEntryId((prev) => (prev === entry.id ? null : entry.id))}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {auditLog && auditLog.total_pages > 1 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-gray-400">
            Page {auditLog.page} of {auditLog.total_pages} ({auditLog.total.toLocaleString()} entries)
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              <ChevronLeft className="h-4 w-4" />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(auditLog.total_pages, p + 1))}
              disabled={page === auditLog.total_pages}
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {/* Dialogs */}
      <RetentionDialog
        isOpen={showRetentionDialog}
        onClose={() => setShowRetentionDialog(false)}
        retention={retention}
        onRetentionChange={handleRetentionChange}
        onCleanup={() => {
          setShowRetentionDialog(false)
          setShowCleanupDialog(true)
        }}
        isPending={updateRetention.isPending}
      />

      <CleanupDialog
        isOpen={showCleanupDialog}
        onClose={() => setShowCleanupDialog(false)}
        retentionDays={retention?.retention_days ?? 0}
        onConfirm={handleCleanup}
        isPending={cleanupAuditLog.isPending}
      />
    </div>
  )
}
