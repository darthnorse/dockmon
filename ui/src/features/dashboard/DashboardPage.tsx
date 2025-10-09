/**
 * Dashboard Page - Phase 4b
 *
 * FEATURES:
 * - View mode selector (Compact | Standard | Expanded)
 * - Drag-and-drop widget dashboard (react-grid-layout)
 * - Real-time monitoring widgets
 * - Persistent layout (localStorage) and view mode (backend)
 * - Responsive grid system
 */

import { GridDashboard } from './GridDashboard'
import { ViewModeSelector } from './components/ViewModeSelector'
import { useViewMode } from './hooks/useViewMode'

export function DashboardPage() {
  const { viewMode, setViewMode, isLoading } = useViewMode()

  return (
    <div className="flex flex-col h-full gap-4 p-4">
      {/* View Mode Selector - Phase 4b */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <ViewModeSelector viewMode={viewMode} onChange={setViewMode} disabled={isLoading} />
      </div>

      {/* Widget Grid - Phase 3b */}
      <GridDashboard />

      {/* View Mode Content - Phase 4b */}
      {viewMode === 'standard' && (
        <div className="p-4 border border-dashed border-border rounded-lg text-center text-muted-foreground">
          Standard mode: Host cards will appear here
        </div>
      )}

      {viewMode === 'expanded' && (
        <div className="p-4 border border-dashed border-border rounded-lg text-center text-muted-foreground">
          Expanded mode: Detailed host cards with inline containers will appear here
        </div>
      )}
    </div>
  )
}
