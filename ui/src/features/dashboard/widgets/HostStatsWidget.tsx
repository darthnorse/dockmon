/**
 * Host Stats Widget
 *
 * Shows total hosts and their connection status
 * Data from /api/hosts endpoint
 */

import { useQuery } from '@tanstack/react-query'
import { Server, CheckCircle2, XCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiClient } from '@/lib/api/client'
import { POLLING_CONFIG } from '@/lib/config/polling'

interface HostStatus {
  online: number
  offline: number
  total: number
}

export function HostStatsWidget() {
  // Backend returns array directly, not wrapped in object
  const { data, isLoading, error } = useQuery<unknown[]>({
    queryKey: ['hosts'],
    queryFn: () => apiClient.get('/hosts'),
    refetchInterval: POLLING_CONFIG.HOST_DATA,
  })

  const stats: HostStatus = {
    online: 0,
    offline: 0,
    total: 0,
  }

  if (data) {
    stats.total = data.length
    // Backend currently doesn't provide host status
    // All registered hosts are considered "online" (able to connect)
    // Offline detection would require ping/healthcheck (future enhancement)
    stats.online = stats.total
    stats.offline = 0
  }

  if (isLoading) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Server className="h-5 w-5" />
            Hosts
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
            <Server className="h-5 w-5" />
            Hosts
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-danger">Failed to load host stats</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Server className="h-5 w-5" />
          Hosts
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Total Count */}
        <div>
          <div className="text-3xl font-semibold">{stats.total}</div>
          <p className="text-sm text-muted-foreground">Registered hosts</p>
        </div>

        {/* Status Breakdown */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-success" />
              <span className="text-sm">Online</span>
            </div>
            <span className="text-sm font-medium">{stats.online}</span>
          </div>

          {stats.offline > 0 && (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <XCircle className="h-4 w-4 text-danger" />
                <span className="text-sm">Offline</span>
              </div>
              <span className="text-sm font-medium">{stats.offline}</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
