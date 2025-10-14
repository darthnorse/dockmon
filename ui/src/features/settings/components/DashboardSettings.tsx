/**
 * Dashboard Settings Component
 * Controls for dashboard appearance and performance
 */

import { useDashboardPrefs } from '@/hooks/useUserPrefs'
import { useGlobalSettings, useUpdateGlobalSettings } from '@/hooks/useSettings'
import { useSimplifiedWorkflow } from '@/lib/hooks/useUserPreferences'
import { ToggleSwitch } from './ToggleSwitch'
import { toast } from 'sonner'

export function DashboardSettings() {
  const { dashboardPrefs, updateDashboardPrefs } = useDashboardPrefs()
  const { data: settings } = useGlobalSettings()
  const updateSettings = useUpdateGlobalSettings()
  const { enabled: simplifiedWorkflow, setEnabled: setSimplifiedWorkflow } = useSimplifiedWorkflow()

  const showKpiBar = dashboardPrefs?.showKpiBar ?? true
  const showStatsWidgets = dashboardPrefs?.showStatsWidgets ?? false
  const optimizedLoading = dashboardPrefs?.optimizedLoading ?? true
  const showContainerAlertsOnHosts = settings?.show_container_alerts_on_hosts ?? false

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

  const handleToggleContainerAlertsOnHosts = async (checked: boolean) => {
    try {
      await updateSettings.mutateAsync({ show_container_alerts_on_hosts: checked })
      toast.success(checked ? 'Container alerts will show on host page' : 'Only host alerts will show on host page')
    } catch (error) {
      toast.error('Failed to update setting')
    }
  }

  const handleToggleSimplifiedWorkflow = (checked: boolean) => {
    setSimplifiedWorkflow(checked)
    toast.success(checked ? 'Simplified workflow enabled - drawers skipped' : 'Simplified workflow disabled - drawers shown')
  }

  return (
    <div className="space-y-6">
      {/* Dashboard Summary */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Dashboard Summary</h3>
          <p className="text-xs text-gray-400 mt-1">
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

      {/* Alerts Display */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Alerts Display</h3>
          <p className="text-xs text-gray-400 mt-1">
            Configure how alerts are displayed on different pages
          </p>
        </div>
        <div className="divide-y divide-border">
          <ToggleSwitch
            id="show-container-alerts-on-hosts"
            label="Show container alerts on host page"
            description="Display alerts from containers in addition to host-level alerts on the host page. When disabled, only host-scoped alerts are shown."
            checked={showContainerAlertsOnHosts}
            onChange={handleToggleContainerAlertsOnHosts}
          />
        </div>
      </div>

      {/* Workflow */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Workflow</h3>
          <p className="text-xs text-gray-400 mt-1">
            Customize how you interact with hosts and containers
          </p>
        </div>
        <div className="divide-y divide-border">
          <ToggleSwitch
            id="simplified-workflow"
            label="Simplified workflow"
            description="Skip the drawer view and open full details modal directly when clicking on hosts or containers. Ideal for users who prefer immediate access to all information."
            checked={simplifiedWorkflow}
            onChange={handleToggleSimplifiedWorkflow}
          />
        </div>
      </div>

      {/* Performance */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Performance</h3>
          <p className="text-xs text-gray-400 mt-1">
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
