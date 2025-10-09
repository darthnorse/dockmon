/**
 * Dashboard Page - Phase 4c
 *
 * FEATURES:
 * - View mode selector (Compact | Standard | Expanded)
 * - Drag-and-drop widget dashboard (react-grid-layout)
 * - Real-time monitoring widgets
 * - Persistent layout (localStorage) and view mode (backend)
 * - Responsive grid system
 * - Host cards below widget grid (Standard/Expanded modes)
 * - WebSocket live sparkline updates (2s interval via query invalidation)
 */

import { GridDashboard } from './GridDashboard'
import { ViewModeSelector } from './components/ViewModeSelector'
import { HostCardContainer } from './components/HostCardContainer'
import { HostCardsGrid } from './HostCardsGrid'
import { useViewMode } from './hooks/useViewMode'
import { useHosts } from '@/features/hosts/hooks/useHosts'

export function DashboardPage() {
  const { viewMode, setViewMode, isLoading: isViewModeLoading } = useViewMode()
  const { data: hosts, isLoading: isHostsLoading } = useHosts()

  return (
    <div className="flex flex-col h-full gap-4 p-4">
      {/* View Mode Selector - Phase 4b */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <ViewModeSelector viewMode={viewMode} onChange={setViewMode} disabled={isViewModeLoading} />
      </div>

      {/* Widget Grid - Phase 3b */}
      <GridDashboard />

      {/* View Mode Content - Phase 4c */}
      {viewMode === 'standard' && (
        <div className="mt-4">
          <h2 className="text-lg font-semibold mb-4">Hosts</h2>
          {isHostsLoading ? (
            <div className="text-muted-foreground">Loading hosts...</div>
          ) : hosts && hosts.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {hosts.map((host) => (
                <HostCardContainer
                  key={host.id}
                  host={{
                    id: host.id,
                    name: host.name,
                    url: host.url,
                    status: host.status as 'online' | 'offline' | 'error',
                    ...(host.tags && { tags: host.tags }),
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="p-8 border border-dashed border-border rounded-lg text-center text-muted-foreground">
              No hosts configured. Add a host to get started.
            </div>
          )}
        </div>
      )}

      {viewMode === 'expanded' && hosts && (
        <HostCardsGrid hosts={hosts.map(h => ({
          id: h.id,
          name: h.name,
          url: h.url,
          status: h.status as 'online' | 'offline' | 'error',
          ...(h.tags && { tags: h.tags }),
        }))} />
      )}
    </div>
  )
}
