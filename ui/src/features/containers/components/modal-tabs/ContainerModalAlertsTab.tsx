/**
 * Container Modal Alerts Tab Component
 *
 * Shows alerts filtered for a specific container
 */

import { useState } from 'react'
import { useAlerts, useResolveAlert, useSnoozeAlert } from '@/features/alerts/hooks/useAlerts'
import type { AlertFilters, AlertState, AlertSeverity } from '@/types/alerts'
import { AlertTriangle, Bell, CheckCircle2, Clock, ChevronLeft, ChevronRight, AlertCircle, Info, ChevronDown } from 'lucide-react'
import { AlertDetailsDrawer } from '@/features/alerts/components/AlertDetailsDrawer'

interface ContainerModalAlertsTabProps {
  containerId: string
}

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

export function ContainerModalAlertsTab({ containerId }: ContainerModalAlertsTabProps) {
  const [filters, setFilters] = useState<AlertFilters>({
    scope_type: 'container',
    scope_id: containerId,
    state: 'open', // Default to showing only open alerts
    page: 1,
    page_size: 10,
  })
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null)
  const [selectedAlertIds, setSelectedAlertIds] = useState<Set<string>>(new Set())
  const [showSnoozeMenu, setShowSnoozeMenu] = useState(false)
  const [showResolveConfirm, setShowResolveConfirm] = useState(false)

  const { data: alertsData, isLoading } = useAlerts(filters, {
    refetchInterval: 30000, // Refresh every 30 seconds
  })
  const resolveAlert = useResolveAlert()
  const snoozeAlert = useSnoozeAlert()

  const alerts = alertsData?.alerts ?? []
  const totalCount = alertsData?.total ?? 0
  const currentPage = alertsData?.page ?? 1
  const totalPages = Math.ceil(totalCount / (filters.page_size ?? 10))

  const handleFilterChange = (key: keyof AlertFilters, value: any) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value === prev[key] ? undefined : value, // Toggle off if same
      page: 1, // Reset to first page
      scope_type: 'container', // Always container
      scope_id: containerId, // Always this container
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
      await resolveAlert.mutateAsync({ alertId, reason: 'Bulk resolved from container modal' })
    }
    setSelectedAlertIds(new Set())
    setShowResolveConfirm(false)
  }

  const getSeverityIcon = (severity: AlertSeverity) => {
    switch (severity) {
      case 'critical':
        return <AlertTriangle className="h-4 w-4 text-red-600" />
      case 'error':
        return <AlertCircle className="h-4 w-4 text-orange-600" />
      case 'warning':
        return <AlertTriangle className="h-4 w-4 text-yellow-600" />
      case 'info':
        return <Info className="h-4 w-4 text-blue-600" />
    }
  }

  const getStateIcon = (state: AlertState) => {
    switch (state) {
      case 'open':
        return <Bell className="h-4 w-4 text-blue-500" />
      case 'snoozed':
        return <Clock className="h-4 w-4 text-yellow-500" />
      case 'resolved':
        return <CheckCircle2 className="h-4 w-4 text-green-500" />
    }
  }

  const formatTimestamp = (ts: string) => {
    const date = new Date(ts)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)

    if (days > 0) return `${days}d ago`
    if (hours > 0) return `${hours}h ago`
    if (minutes > 0) return `${minutes}m ago`
    return 'Just now'
  }

  if (isLoading) {
    return <div className="p-6 text-center text-muted-foreground">Loading alerts...</div>
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="p-4 border-b border-border bg-surface-0">
        <div className="flex items-center gap-2 flex-wrap">
          {/* State Filter */}
          <div className="flex gap-1">
            {STATE_OPTIONS.map((option) => {
              const Icon = option.icon
              const isActive = filters.state === option.value
              return (
                <button
                  key={option.value}
                  onClick={() => handleFilterChange('state', option.value)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
                    isActive
                      ? 'bg-accent text-white'
                      : 'bg-surface-1 text-muted-foreground hover:bg-surface-2'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {option.label}
                </button>
              )
            })}
          </div>

          {/* Severity Filter */}
          <div className="flex gap-1 ml-auto">
            {SEVERITY_OPTIONS.map((option) => {
              const isActive = filters.severity === option.value
              return (
                <button
                  key={option.value}
                  onClick={() => handleFilterChange('severity', option.value)}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    isActive
                      ? `${option.color} bg-surface-2`
                      : 'text-muted-foreground bg-surface-1 hover:bg-surface-2'
                  }`}
                >
                  {option.label}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Bulk Actions */}
      {selectedAlertIds.size > 0 && (
        <div className="p-3 border-b border-border bg-surface-1 flex items-center gap-3">
          <span className="text-sm text-foreground">
            {selectedAlertIds.size} selected
          </span>
          <div className="flex gap-2">
            {/* Snooze dropdown */}
            <div className="relative">
              <button
                onClick={() => setShowSnoozeMenu(!showSnoozeMenu)}
                className="flex items-center gap-1 px-3 py-1 rounded-md bg-surface-2 text-foreground text-sm hover:bg-surface-3 transition-colors"
              >
                <Clock className="h-4 w-4" />
                Snooze
                <ChevronDown className="h-3 w-3" />
              </button>
              {showSnoozeMenu && (
                <div className="absolute top-full left-0 mt-1 z-10 rounded-md border border-border bg-surface-1 shadow-lg overflow-hidden">
                  {SNOOZE_DURATIONS.map((duration) => (
                    <button
                      key={duration.value}
                      onClick={() => handleBulkSnooze(duration.value)}
                      className="block w-full px-4 py-2 text-left text-sm text-foreground hover:bg-surface-2 whitespace-nowrap"
                    >
                      {duration.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Resolve button */}
            <button
              onClick={() => setShowResolveConfirm(true)}
              className="flex items-center gap-1 px-3 py-1 rounded-md bg-success/20 text-success text-sm hover:bg-success/30 transition-colors"
            >
              <CheckCircle2 className="h-4 w-4" />
              Resolve
            </button>

            {/* Resolve confirmation */}
            {showResolveConfirm && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
                <div className="bg-surface-1 rounded-lg p-6 max-w-md border border-border">
                  <h3 className="text-lg font-semibold text-foreground mb-2">Resolve Alerts?</h3>
                  <p className="text-sm text-muted-foreground mb-4">
                    Are you sure you want to resolve {selectedAlertIds.size} alert{selectedAlertIds.size > 1 ? 's' : ''}?
                  </p>
                  <div className="flex gap-3 justify-end">
                    <button
                      onClick={() => setShowResolveConfirm(false)}
                      className="px-4 py-2 rounded-md bg-surface-2 text-foreground hover:bg-surface-3 transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleBulkResolve}
                      className="px-4 py-2 rounded-md bg-success text-white hover:bg-success/90 transition-colors"
                    >
                      Resolve
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Alerts List */}
      <div className="flex-1 overflow-y-auto">
        {alerts.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            <Bell className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p className="text-lg">No alerts found</p>
            <p className="text-sm mt-1">This container has no {filters.state} alerts</p>
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-surface-1 sticky top-0">
              <tr className="border-b border-border">
                <th className="w-10 p-3">
                  <input
                    type="checkbox"
                    checked={selectedAlertIds.size === alerts.length && alerts.length > 0}
                    onChange={(e) => handleSelectAll(e.target.checked)}
                    className="rounded border-gray-600"
                  />
                </th>
                <th className="text-left p-3 text-sm font-medium text-muted-foreground">Severity</th>
                <th className="text-left p-3 text-sm font-medium text-muted-foreground">Type</th>
                <th className="text-left p-3 text-sm font-medium text-muted-foreground">Message</th>
                <th className="text-left p-3 text-sm font-medium text-muted-foreground">Last Seen</th>
                <th className="text-left p-3 text-sm font-medium text-muted-foreground">State</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert) => (
                <tr
                  key={alert.id}
                  onClick={() => setSelectedAlertId(alert.id)}
                  className="border-b border-border hover:bg-surface-1 cursor-pointer transition-colors"
                >
                  <td className="p-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedAlertIds.has(alert.id)}
                      onChange={(e) => handleSelectAlert(alert.id, e.target.checked)}
                      className="rounded border-gray-600"
                    />
                  </td>
                  <td className="p-3">{getSeverityIcon(alert.severity)}</td>
                  <td className="p-3 text-sm text-foreground font-medium">{alert.kind}</td>
                  <td className="p-3 text-sm text-foreground">{alert.title}</td>
                  <td className="p-3 text-sm text-muted-foreground">{formatTimestamp(alert.last_seen)}</td>
                  <td className="p-3">{getStateIcon(alert.state)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="p-3 border-t border-border bg-surface-0 flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            Page {currentPage} of {totalPages} ({totalCount} total)
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={currentPage === 1}
              className="p-2 rounded-md bg-surface-1 text-foreground hover:bg-surface-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={currentPage === totalPages}
              className="p-2 rounded-md bg-surface-1 text-foreground hover:bg-surface-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Alert Details Drawer */}
      {selectedAlertId && (
        <AlertDetailsDrawer
          alertId={selectedAlertId}
          onClose={() => setSelectedAlertId(null)}
        />
      )}
    </div>
  )
}
