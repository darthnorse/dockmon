/**
 * Container Stats Widget - Phase 4 Enhanced
 *
 * Shows total containers and their status breakdown
 * Clickable: Total → /containers, Status rows → /containers?state=X
 * Data from /api/containers endpoint
 */

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Container, Activity, Square, Circle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiClient } from '@/lib/api/client'
import { POLLING_CONFIG } from '@/lib/config/polling'

interface ContainerStatus {
  running: number
  stopped: number
  paused: number
  total: number
}

export function ContainerStatsWidget() {
  const navigate = useNavigate()

  // Backend returns array directly, not wrapped in object
  const { data, isLoading, error } = useQuery<unknown[]>({
    queryKey: ['containers'],
    queryFn: () => apiClient.get('/containers'),
    refetchInterval: POLLING_CONFIG.CONTAINER_DATA,
  })

  // Calculate stats from container data
  const stats: ContainerStatus = {
    running: 0,
    stopped: 0,
    paused: 0,
    total: 0,
  }

  if (data) {
    stats.total = data.length
    // Parse actual container states from backend data
    data.forEach((container: any) => {
      if (container.state === 'running') stats.running++
      else if (container.state === 'paused') stats.paused++
      else stats.stopped++ // stopped, exited, dead, etc.
    })
  }

  if (isLoading) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Container className="h-5 w-5" />
            Containers
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-3">
            <div className="h-12 rounded bg-muted" />
            <div className="h-8 rounded bg-muted" />
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
            <Container className="h-5 w-5" />
            Containers
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-danger">Failed to load container stats</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Container className="h-5 w-5" />
          Containers
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Total Count - Clickable */}
        <div
          className="cursor-pointer transition-colors hover:text-accent"
          onClick={() => navigate('/containers')}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              navigate('/containers')
            }
          }}
          aria-label={`View all ${stats.total} containers`}
        >
          <div className="text-3xl font-semibold">{stats.total}</div>
          <p className="text-sm text-muted-foreground">Total containers</p>
        </div>

        {/* Status Breakdown - Each row clickable with state filter */}
        <div className="space-y-2">
          <div
            className="flex items-center justify-between cursor-pointer transition-colors hover:text-success rounded px-2 -mx-2 py-1 hover:bg-success/10"
            onClick={(e) => {
              e.stopPropagation()
              navigate('/containers?state=running')
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                navigate('/containers?state=running')
              }
            }}
            aria-label={`View ${stats.running} running containers`}
          >
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-success" />
              <span className="text-sm">Running</span>
            </div>
            <span className="text-sm font-medium">{stats.running}</span>
          </div>

          <div
            className="flex items-center justify-between cursor-pointer transition-colors hover:text-muted-foreground rounded px-2 -mx-2 py-1 hover:bg-muted"
            onClick={(e) => {
              e.stopPropagation()
              navigate('/containers?state=stopped')
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                navigate('/containers?state=stopped')
              }
            }}
            aria-label={`View ${stats.stopped} stopped containers`}
          >
            <div className="flex items-center gap-2">
              <Square className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm">Stopped</span>
            </div>
            <span className="text-sm font-medium">{stats.stopped}</span>
          </div>

          {stats.paused > 0 && (
            <div
              className="flex items-center justify-between cursor-pointer transition-colors hover:text-warning rounded px-2 -mx-2 py-1 hover:bg-warning/10"
              onClick={(e) => {
                e.stopPropagation()
                navigate('/containers?state=paused')
              }}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  navigate('/containers?state=paused')
                }
              }}
              aria-label={`View ${stats.paused} paused containers`}
            >
              <div className="flex items-center gap-2">
                <Circle className="h-4 w-4 text-warning" />
                <span className="text-sm">Paused</span>
              </div>
              <span className="text-sm font-medium">{stats.paused}</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
