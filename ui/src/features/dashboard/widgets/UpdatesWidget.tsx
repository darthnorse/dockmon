/**
 * Updates Widget - Phase 4
 *
 * Shows containers with updates available
 * Placeholder: Update detection feature not yet implemented
 * Click → Navigate to /updates (placeholder route)
 */

import { useNavigate } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function UpdatesWidget() {
  const navigate = useNavigate()

  // Placeholder: Update detection not implemented yet
  // Future: Will fetch from /api/updates or similar endpoint
  const updatesAvailable = 0

  return (
    <Card
      className="h-full cursor-pointer transition-all hover:shadow-md hover:border-info/50"
      onClick={() => navigate('/updates')}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          navigate('/updates')
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
          <div className="text-3xl font-semibold text-info">{updatesAvailable}</div>
          <p className="text-sm text-muted-foreground">Available</p>
        </div>

        {/* Placeholder message */}
        <div className="text-xs text-muted-foreground">
          Update detection not yet implemented
        </div>
      </CardContent>
    </Card>
  )
}
