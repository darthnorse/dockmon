/**
 * Updates Widget - Phase 4
 *
 * Shows containers with updates available
 * Click → Navigate to /containers (container list)
 */

import { useNavigate } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useUpdatesSummary } from '@/features/containers/hooks/useContainerUpdates'

export function UpdatesWidget() {
  const navigate = useNavigate()
  const { data: updatesSummary, isLoading } = useUpdatesSummary()

  const updatesAvailable = updatesSummary?.total_updates || 0

  return (
    <Card
      className="h-full cursor-pointer transition-all hover:shadow-md hover:border-info/50"
      onClick={() => navigate('/containers?updates=true')}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          navigate('/containers?updates=true')
        }
      }}
      aria-label={`View ${updatesAvailable} container updates available`}
    >
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <RefreshCw className="h-5 w-5" />
          Updates
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Total Count */}
        <div>
          {isLoading ? (
            <div className="text-3xl font-semibold text-muted-foreground animate-pulse">-</div>
          ) : (
            <div className="text-3xl font-semibold text-info">{updatesAvailable}</div>
          )}
          <p className="text-sm text-muted-foreground">Available</p>
        </div>

        {/* Status message */}
        <div className="text-xs text-muted-foreground">
          {updatesAvailable > 0
            ? `${updatesAvailable} container${updatesAvailable > 1 ? 's' : ''} ready to update`
            : 'All containers up to date'}
        </div>
      </CardContent>
    </Card>
  )
}
