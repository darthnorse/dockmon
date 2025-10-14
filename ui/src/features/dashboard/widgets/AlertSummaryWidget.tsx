/**
 * Alert Summary Widget
 *
 * Shows active alerts grouped by severity
 * Data from v2 alerts API (/api/alerts/stats/)
 */

import { Bell, AlertTriangle, AlertCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAlertStats } from '@/features/alerts/hooks/useAlerts'

export function AlertSummaryWidget() {
  const { data: alertStats, isLoading, error } = useAlertStats()

  // Calculate active alerts (open only, snoozed will become open when they wake up)
  const activeCount = alertStats?.by_state.open || 0
  const criticalCount = alertStats?.by_severity.critical || 0
  const errorCount = alertStats?.by_severity.error || 0
  const warningCount = alertStats?.by_severity.warning || 0

  if (isLoading) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Bell className="h-5 w-5" />
            Active Alerts
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-3">
            <div className="h-12 rounded bg-muted" />
            <div className="h-8 rounded bg-muted" />
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Bell className="h-5 w-5" />
            Active Alerts
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-danger">Failed to load alerts</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Bell className="h-5 w-5" />
          Active Alerts
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Total Count */}
        <div>
          <div className="text-3xl font-semibold">{activeCount}</div>
          <p className="text-sm text-muted-foreground">Active alerts</p>
        </div>

        {/* Severity Breakdown */}
        {activeCount > 0 && (
          <div className="space-y-2">
            {criticalCount > 0 && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 text-danger" />
                  <span className="text-sm">Critical</span>
                </div>
                <span className="text-sm font-medium">{criticalCount}</span>
              </div>
            )}

            {errorCount > 0 && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 text-red-400" />
                  <span className="text-sm">Error</span>
                </div>
                <span className="text-sm font-medium">{errorCount}</span>
              </div>
            )}

            {warningCount > 0 && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-warning" />
                  <span className="text-sm">Warning</span>
                </div>
                <span className="text-sm font-medium">{warningCount}</span>
              </div>
            )}
          </div>
        )}

        {activeCount === 0 && (
          <p className="text-sm text-success">No active alerts</p>
        )}
      </CardContent>
    </Card>
  )
}
