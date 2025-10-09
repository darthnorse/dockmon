/**
 * Dashboard Settings Component
 * Controls for dashboard appearance and performance
 */

import { useDashboardPrefs } from '@/hooks/useUserPrefs'
import { ToggleSwitch } from './ToggleSwitch'
import { toast } from 'sonner'

export function DashboardSettings() {
  const { dashboardPrefs, updateDashboardPrefs } = useDashboardPrefs()

  const showKpiBar = dashboardPrefs?.showKpiBar ?? true
  const showStatsWidgets = dashboardPrefs?.showStatsWidgets ?? false
  const optimizedLoading = dashboardPrefs?.optimizedLoading ?? true

  const handleToggleKpiBar = (checked: boolean) => {
    updateDashboardPrefs({ showKpiBar: checked })
    toast.success(checked ? 'KPI bar enabled' : 'KPI bar disabled')
  }

  const handleToggleStatsWidgets = (checked: boolean) => {
    updateDashboardPrefs({ showStatsWidgets: checked })
    toast.success(checked ? 'Stats widgets enabled' : 'Stats widgets disabled')
  }

  const handleToggleOptimizedLoading = (checked: boolean) => {
    updateDashboardPrefs({ optimizedLoading: checked })
    toast.success(checked ? 'Optimized loading enabled' : 'Optimized loading disabled')
  }

  return (
    <div className="space-y-6">
      {/* Dashboard Summary Section */}
      <div className="bg-surface border border-border rounded-lg p-6">
        <div className="mb-4">
          <h2 className="text-lg font-semibold">Dashboard Summary</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Control which elements appear on your dashboard
          </p>
        </div>

        <div className="divide-y divide-border">
          <ToggleSwitch
            id="show-kpi-bar"
            label="Show KPI bar"
            description="Display the summary bar at the top of the dashboard showing total hosts, containers, and system health"
            checked={showKpiBar}
            onChange={handleToggleKpiBar}
          />

          <ToggleSwitch
            id="show-stats-widgets"
            label="Show stats widgets"
            description="Display detailed statistics widgets on the dashboard"
            checked={showStatsWidgets}
            onChange={handleToggleStatsWidgets}
          />
        </div>
      </div>

      {/* Performance Section */}
      <div className="bg-surface border border-border rounded-lg p-6">
        <div className="mb-4">
          <h2 className="text-lg font-semibold">Performance</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Optimize dashboard performance for better battery life and responsiveness
          </p>
        </div>

        <div className="divide-y divide-border">
          <ToggleSwitch
            id="optimized-loading"
            label="Optimized dashboard loading"
            description="Pause sparkline updates for host cards scrolled out of view. Saves CPU and battery on large dashboards (50+ hosts). Disable for continuous updates on all hosts."
            checked={optimizedLoading}
            onChange={handleToggleOptimizedLoading}
          />
        </div>
      </div>
    </div>
  )
}
