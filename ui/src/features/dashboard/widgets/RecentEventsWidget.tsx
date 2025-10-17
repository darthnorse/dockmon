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
  id: number
  event_type: string
  category: string
  severity: string
  title: string
  message?: string
  container_name?: string | null
  host_name?: string | null
  timestamp: string
}

export function RecentEventsWidget() {
  const { data, isLoading, error } = useQuery<{ events: DockerEvent[] }>({
    queryKey: ['events', 'recent'],
    queryFn: () => apiClient.get('/events?limit=10'),
    staleTime: 10000, // Cache for 10s
    // No refetchInterval needed - WebSocket 'new_event' messages trigger invalidation
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
              // Determine icon and color based on title/event_type
              let Icon = Activity
              let iconColor = 'text-muted-foreground'

              const titleLower = event.title.toLowerCase()
              if (titleLower.includes('start') || titleLower.includes('running')) {
                Icon = PlayCircle
                iconColor = 'text-success'
              } else if (titleLower.includes('stop') || titleLower.includes('die') || titleLower.includes('exit')) {
                Icon = StopCircle
                iconColor = 'text-danger'
              } else if (event.category === 'container') {
                Icon = Container
              }

              // Display name: container name if available, otherwise use title
              const displayName = event.container_name || event.title

              return (
                <div key={event.id} className="flex items-start gap-3">
                  <Icon className={`mt-0.5 h-4 w-4 flex-shrink-0 ${iconColor}`} />
                  <div className="flex-1 overflow-hidden">
                    <p className="truncate text-sm font-medium">
                      {displayName}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(event.timestamp).toLocaleTimeString()}
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
