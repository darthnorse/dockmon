/**
 * Alert Summary Widget
 *
 * Shows active alerts grouped by severity
 * Data from /api/alerts endpoint
 */

import { useQuery } from '@tanstack/react-query'
import { Bell, AlertTriangle, AlertCircle, Info } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiClient } from '@/lib/api/client'

interface Alert {
  id: string
  severity: 'critical' | 'warning' | 'info'
  message: string
  timestamp: string
}

interface AlertStats {
  critical: number
  warning: number
  info: number
  total: number
}

export function AlertSummaryWidget() {
  const { data, isLoading, error } = useQuery<{ alerts: Alert[] }>({
    queryKey: ['alerts', 'active'],
    queryFn: () => apiClient.get('/alerts?status=active'),
    refetchInterval: 5000, // Refresh every 5s
  })

  const stats: AlertStats = {
    critical: 0,
    warning: 0,
    info: 0,
    total: 0,
  }

  if (data?.alerts) {
    stats.total = data.alerts.length
    data.alerts.forEach((alert) => {
      if (alert.severity === 'critical') stats.critical++
      else if (alert.severity === 'warning') stats.warning++
      else if (alert.severity === 'info') stats.info++
    })
  }

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
          <div className="text-3xl font-semibold">{stats.total}</div>
          <p className="text-sm text-muted-foreground">Active alerts</p>
        </div>

        {/* Severity Breakdown */}
        {stats.total > 0 && (
          <div className="space-y-2">
            {stats.critical > 0 && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 text-danger" />
                  <span className="text-sm">Critical</span>
                </div>
                <span className="text-sm font-medium">{stats.critical}</span>
              </div>
            )}

            {stats.warning > 0 && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-warning" />
                  <span className="text-sm">Warning</span>
                </div>
                <span className="text-sm font-medium">{stats.warning}</span>
              </div>
            )}

            {stats.info > 0 && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Info className="h-4 w-4 text-info" />
                  <span className="text-sm">Info</span>
                </div>
                <span className="text-sm font-medium">{stats.info}</span>
              </div>
            )}
          </div>
        )}

        {stats.total === 0 && (
          <p className="text-sm text-success">No active alerts</p>
        )}
      </CardContent>
    </Card>
  )
}
