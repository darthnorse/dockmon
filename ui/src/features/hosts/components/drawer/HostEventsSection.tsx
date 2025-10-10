/**
 * HostEventsSection Component
 *
 * Displays recent Docker events for a host
 * TODO: Implement when Events API is available (Phase 7)
 */

import { Calendar, ArrowRight } from 'lucide-react'
import { DrawerSection } from '@/components/ui/drawer'
import { Link } from 'react-router-dom'

interface HostEventsSectionProps {
  hostId: string
}

export function HostEventsSection({ hostId }: HostEventsSectionProps) {
  // TODO: Replace with actual events hook when Events API is implemented
  const events: any[] = []

  return (
    <DrawerSection title="Recent Events">
      {events.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          <Calendar className="h-12 w-12 mx-auto mb-3 opacity-50" />
          <p className="text-sm">No recent events</p>
          <p className="text-xs mt-1">
            Events will appear here once the Events system is implemented
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* TODO: Render events when available */}
          {events.map((_, index) => (
            <div key={index} className="p-3 rounded-lg bg-muted">
              {/* Event content */}
            </div>
          ))}

          {/* View All Link */}
          <Link
            to={`/events?host=${hostId}`}
            className="flex items-center justify-center gap-2 p-3 rounded-lg border border-border hover:bg-muted transition-colors text-sm text-muted-foreground hover:text-foreground"
          >
            <span>View all events for this host</span>
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}
    </DrawerSection>
  )
}
