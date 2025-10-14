/**
 * AlertsPage Component
 *
 * Main alerts view with filtering and list display
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAlerts, useAlertStats, useResolveAlert, useSnoozeAlert } from './hooks/useAlerts'
import type { AlertFilters, AlertState, AlertSeverity, AlertScope } from '@/types/alerts'
import { AlertTriangle, Bell, CheckCircle2, Clock, ChevronLeft, ChevronRight, AlertCircle, Info, ChevronDown, Settings } from 'lucide-react'
import { AlertDetailsDrawer } from './components/AlertDetailsDrawer'

const SNOOZE_DURATIONS = [
  { label: '15 minutes', value: 15 },
  { label: '1 hour', value: 60 },
  { label: '4 hours', value: 240 },
  { label: '24 hours', value: 1440 },
]

const STATE_OPTIONS: { value: AlertState; label: string; icon: any }[] = [
  { value: 'open', label: 'Open', icon: AlertCircle },
  { value: 'snoozed', label: 'Snoozed', icon: Clock },
  { value: 'resolved', label: 'Resolved', icon: CheckCircle2 },
]

const SEVERITY_OPTIONS: { value: AlertSeverity; label: string; color: string }[] = [
  { value: 'critical', label: 'Critical', color: 'text-red-600' },
  { value: 'error', label: 'Error', color: 'text-orange-600' },
  { value: 'warning', label: 'Warning', color: 'text-yellow-600' },
  { value: 'info', label: 'Info', color: 'text-blue-600' },
]

const SCOPE_OPTIONS: { value: AlertScope; label: string }[] = [
  { value: 'host', label: 'Host' },
  { value: 'container', label: 'Container' },
  { value: 'group', label: 'Group' },
]

export function AlertsPage() {
  const [filters, setFilters] = useState<AlertFilters>({
    state: 'open', // Default to showing only open alerts
    page: 1,
    page_size: 20,
  })
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null)
  const [selectedAlertIds, setSelectedAlertIds] = useState<Set<string>>(new Set())
  const [showSnoozeMenu, setShowSnoozeMenu] = useState(false)
  const [showResolveConfirm, setShowResolveConfirm] = useState(false)

  const { data: alertsData, isLoading } = useAlerts(filters, {
    refetchInterval: 30000, // Refresh every 30 seconds
  })
  const { data: stats } = useAlertStats()
  const resolveAlert = useResolveAlert()
  const snoozeAlert = useSnoozeAlert()

  const alerts = alertsData?.alerts ?? []
  const totalCount = alertsData?.total ?? 0
  const currentPage = alertsData?.page ?? 1
  const totalPages = Math.ceil(totalCount / (filters.page_size ?? 20))

  const handleFilterChange = (key: keyof AlertFilters, value: any) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value === prev[key] ? undefined : value, // Toggle off if same
      page: 1, // Reset to first page
    }))
  }

  const handlePageChange = (newPage: number) => {
    setFilters((prev) => ({ ...prev, page: newPage }))
  }

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedAlertIds(new Set(alerts.map((a) => a.id)))
    } else {
      setSelectedAlertIds(new Set())
    }
  }

  const handleSelectAlert = (alertId: string, checked: boolean) => {
    const newSelection = new Set(selectedAlertIds)
    if (checked) {
      newSelection.add(alertId)
    } else {
      newSelection.delete(alertId)
    }
    setSelectedAlertIds(newSelection)
  }

  const handleBulkSnooze = async (minutes: number) => {
    for (const alertId of selectedAlertIds) {
      await snoozeAlert.mutateAsync({ alertId, durationMinutes: minutes })
    }
    setSelectedAlertIds(new Set())
    setShowSnoozeMenu(false)
  }

  const handleBulkResolve = async () => {
    for (const alertId of selectedAlertIds) {
      await resolveAlert.mutateAsync({ alertId })
    }
    setSelectedAlertIds(new Set())
    setShowResolveConfirm(false)
  }

  const getSeverityColor = (severity: AlertSeverity) => {
    switch (severity) {
      case 'critical':
        return 'text-red-600 bg-red-50 border-red-200'
      case 'error':
        return 'text-orange-600 bg-orange-50 border-orange-200'
      case 'warning':
        return 'text-yellow-600 bg-yellow-50 border-yellow-200'
      case 'info':
        return 'text-blue-600 bg-blue-50 border-blue-200'
    }
  }

  const getStateColor = (state: AlertState) => {
    switch (state) {
      case 'open':
        return 'text-red-600 bg-red-50'
      case 'snoozed':
        return 'text-blue-600 bg-blue-50'
      case 'resolved':
        return 'text-green-600 bg-green-50'
    }
  }

  const formatRelativeTime = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
  }

  return (
    <div className="flex h-full flex-col bg-[#0a0e14]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-800 bg-[#0d1117] px-6 py-4">
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-xl font-semibold text-white">Alerts</h1>
            <p className="text-sm text-gray-400">Monitor and manage system alerts</p>
          </div>
          <Link
            to="/alerts/rules"
            className="flex items-center gap-2 rounded-md bg-gray-800 px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-gray-700"
          >
            <Settings className="h-4 w-4" />
            Manage Rules
          </Link>
        </div>

        {/* Stats KPIs */}
        {stats && (
          <div className="flex gap-6">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-red-500" />
              <div>
                <div className="text-xs text-gray-400">Critical</div>
                <div className="text-lg font-semibold text-white">{stats.by_severity.critical}</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-orange-500" />
              <div>
                <div className="text-xs text-gray-400">Error</div>
                <div className="text-lg font-semibold text-white">{stats.by_severity.error}</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Bell className="h-5 w-5 text-yellow-500" />
              <div>
                <div className="text-xs text-gray-400">Warning</div>
                <div className="text-lg font-semibold text-white">{stats.by_severity.warning}</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-green-500" />
              <div>
                <div className="text-xs text-gray-400">Open</div>
                <div className="text-lg font-semibold text-white">{stats.by_state.open}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="border-b border-gray-800 bg-[#0d1117] px-6 py-3">
        <div className="flex flex-wrap gap-3">
          {/* State Filter */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">State:</span>
            {STATE_OPTIONS.map((option) => (
              <button
                key={option.value}
                onClick={() => handleFilterChange('state', option.value)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                  filters.state === option.value
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                }`}
              >
                <option.icon className="h-4 w-4" />
                {option.label}
              </button>
            ))}
          </div>

          {/* Severity Filter */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">Severity:</span>
            {SEVERITY_OPTIONS.map((option) => (
              <button
                key={option.value}
                onClick={() => handleFilterChange('severity', option.value)}
                className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                  filters.severity === option.value
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>

          {/* Scope Filter */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">Scope:</span>
            {SCOPE_OPTIONS.map((option) => (
              <button
                key={option.value}
                onClick={() => handleFilterChange('scope_type', option.value)}
                className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                  filters.scope_type === option.value
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Alerts List */}
      <div className={`flex-1 overflow-auto ${selectedAlertIds.size > 0 ? 'pb-32' : ''}`}>
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-gray-400">
            Loading alerts...
          </div>
        ) : alerts.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-gray-400">
            <Info className="mb-2 h-12 w-12" />
            <p className="text-lg">No alerts found</p>
            <p className="text-sm">Try adjusting your filters</p>
          </div>
        ) : (
          <>
            {/* Table Header */}
            <div className="flex items-center border-b border-gray-800 bg-gray-900/30 px-6 py-3">
              <input
                type="checkbox"
                checked={selectedAlertIds.size === alerts.length && alerts.length > 0}
                onChange={(e) => handleSelectAll(e.target.checked)}
                className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0"
              />
              <div className="ml-6 flex-1 text-sm font-medium text-gray-400">Alert</div>
            </div>

            {/* Table Body */}
            <div className="divide-y divide-gray-800">
              {alerts.map((alert) => {
                const isDimmed = alert.state === 'resolved' || alert.state === 'snoozed'
                return (
                  <div
                    key={alert.id}
                    className={`flex items-start border-l-4 px-6 py-4 transition-colors hover:bg-gray-900/50 ${
                      isDimmed ? 'opacity-60' : ''
                    }`}
                    style={{
                      borderLeftColor:
                        alert.severity === 'critical'
                          ? '#dc2626'
                          : alert.severity === 'error'
                            ? '#ea580c'
                            : alert.severity === 'warning'
                              ? '#ca8a04'
                              : '#2563eb',
                    }}
                  >
                  {/* Checkbox */}
                  <div className="flex items-start">
                    <input
                      type="checkbox"
                      checked={selectedAlertIds.has(alert.id)}
                      onChange={(e) => {
                        e.stopPropagation()
                        handleSelectAlert(alert.id, e.target.checked)
                      }}
                      className="h-4 w-4 mt-1 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0"
                    />
                  </div>

                  {/* Alert Content */}
                  <button
                    onClick={() => setSelectedAlertId(alert.id)}
                    className="ml-6 flex-1 text-left"
                  >
                    <div className="flex items-center gap-3">
                      <h3 className="font-medium text-white">{alert.title}</h3>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${getStateColor(alert.state)}`}>
                        {alert.state}
                      </span>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs font-medium ${getSeverityColor(alert.severity)}`}
                      >
                        {alert.severity}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-gray-400">{alert.message}</p>
                    <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
                      <span>First seen: {formatRelativeTime(alert.first_seen)}</span>
                      <span>Last seen: {formatRelativeTime(alert.last_seen)}</span>
                      <span>Occurrences: {alert.occurrences}</span>
                      {alert.current_value != null && alert.threshold != null && (
                        <span>
                          Value: {alert.current_value.toFixed(1)} / Threshold: {alert.threshold.toFixed(1)}
                        </span>
                      )}
                    </div>
                  </button>
                </div>
                )
              })}
            </div>
          </>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-gray-800 bg-[#0d1117] px-6 py-3">
          <div className="text-sm text-gray-400">
            Showing {(currentPage - 1) * (filters.page_size ?? 20) + 1} to{' '}
            {Math.min(currentPage * (filters.page_size ?? 20), totalCount)} of {totalCount} alerts
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={currentPage === 1}
              className="rounded-md bg-gray-800 p-2 text-gray-300 transition-colors hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm text-gray-400">
              Page {currentPage} of {totalPages}
            </span>
            <button
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={currentPage === totalPages}
              className="rounded-md bg-gray-800 p-2 text-gray-300 transition-colors hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Bulk Action Bar */}
      {selectedAlertIds.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-gray-700 bg-[#0d1117] px-6 py-4 shadow-2xl">
          <div className="flex items-center justify-between">
            <div className="text-sm text-gray-300">
              {selectedAlertIds.size} alert{selectedAlertIds.size !== 1 ? 's' : ''} selected
            </div>
            <div className="flex items-center gap-3">
              {/* Snooze Dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowSnoozeMenu(!showSnoozeMenu)}
                  className="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
                >
                  <Clock className="h-4 w-4" />
                  <span>Snooze</span>
                  <ChevronDown className="h-4 w-4" />
                </button>

                {showSnoozeMenu && (
                  <>
                    <div className="fixed inset-0 z-[45]" onClick={() => setShowSnoozeMenu(false)} />
                    <div className="absolute bottom-full left-0 mb-2 w-48 rounded-lg bg-gray-800 shadow-xl border border-gray-700 py-1 z-[46]">
                      {SNOOZE_DURATIONS.map((duration) => (
                        <button
                          key={duration.value}
                          onClick={() => handleBulkSnooze(duration.value)}
                          className="w-full px-4 py-2 text-left text-sm text-gray-300 transition-colors hover:bg-gray-700"
                        >
                          {duration.label}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {/* Resolve Button */}
              <button
                onClick={() => setShowResolveConfirm(true)}
                className="flex items-center gap-2 rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-green-700"
              >
                <CheckCircle2 className="h-4 w-4" />
                <span>Resolve</span>
              </button>

              {/* Cancel Button */}
              <button
                onClick={() => setSelectedAlertIds(new Set())}
                className="rounded-md bg-gray-800 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-700"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Resolve Confirmation Dialog */}
      {showResolveConfirm && (
        <div className="fixed inset-0 bg-black/70 z-[60] flex items-center justify-center p-4">
          <div className="bg-[#0d1117] border border-gray-700 rounded-lg shadow-2xl max-w-md w-full p-6">
            <div className="flex items-start gap-4 mb-4">
              <div className="flex-shrink-0 w-12 h-12 rounded-full bg-green-500/10 flex items-center justify-center">
                <CheckCircle2 className="h-6 w-6 text-green-500" />
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold mb-2 text-white">Resolve Alerts</h3>
                <p className="text-sm text-gray-400">
                  Are you sure you want to mark {selectedAlertIds.size} alert{selectedAlertIds.size !== 1 ? 's' : ''} as resolved?
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => setShowResolveConfirm(false)}
                className="px-4 py-2 rounded-md bg-gray-800 text-gray-300 hover:bg-gray-700 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkResolve}
                disabled={resolveAlert.isPending}
                className="px-4 py-2 rounded-md bg-green-600 text-white hover:bg-green-700 transition-colors disabled:opacity-50"
              >
                {resolveAlert.isPending ? 'Resolving...' : 'Resolve Alerts'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Alert Details Drawer */}
      {selectedAlertId && (
        <AlertDetailsDrawer alertId={selectedAlertId} onClose={() => setSelectedAlertId(null)} />
      )}
    </div>
  )
}
