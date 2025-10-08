/**
 * Recent Events Widget
 *
 * Shows the latest Docker events (container start/stop, etc.)
 * Data from /api/events endpoint
 */

import { useQuery } from '@tanstack/react-query'
import { Activity, Container, PlayCircle, StopCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiClient } from '@/lib/api/client'

interface DockerEvent {
  id: string
  type: string
  action: string
  container_name?: string
  timestamp: string
}

export function RecentEventsWidget() {
  const { data, isLoading, error } = useQuery<{ events: DockerEvent[] }>({
    queryKey: ['events', 'recent'],
    queryFn: () => apiClient.get('/events?limit=5'),
    refetchInterval: 3000, // Refresh every 3s for real-time feel
  })

  if (isLoading) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-5 w-5" />
            Recent Events
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-12 rounded bg-muted" />
            ))}
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
            <Activity className="h-5 w-5" />
            Recent Events
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-danger">Failed to load events</p>
        </CardContent>
      </Card>
    )
  }

  const events = data?.events || []

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="flex-shrink-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="h-5 w-5" />
          Recent Events
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-auto">
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recent events</p>
        ) : (
          <div className="space-y-3">
            {events.map((event) => {
              // Determine icon and color based on action
              let Icon = Container
              let iconColor = 'text-muted-foreground'

              if (event.action === 'start') {
                Icon = PlayCircle
                iconColor = 'text-success'
              } else if (event.action === 'stop' || event.action === 'die') {
                Icon = StopCircle
                iconColor = 'text-danger'
              }

              return (
                <div key={event.id} className="flex items-start gap-3">
                  <Icon className={`mt-0.5 h-4 w-4 flex-shrink-0 ${iconColor}`} />
                  <div className="flex-1 overflow-hidden">
                    <p className="truncate text-sm font-medium">
                      {event.container_name || 'Unknown container'}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {event.action} • {new Date(event.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
