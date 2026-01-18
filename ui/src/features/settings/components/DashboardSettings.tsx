/**
 * Dashboard Settings Component
 * Controls for dashboard appearance and performance
 */

import { useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'
import { useSimplifiedWorkflow } from '@/lib/hooks/useUserPreferences'
import { useGlobalSettings, useUpdateGlobalSettings } from '@/hooks/useSettings'
import { ToggleSwitch } from './ToggleSwitch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { toast } from 'sonner'

const EDITOR_THEMES = [
  { value: 'github-dark', label: 'GitHub Dark' },
  { value: 'vscode-dark', label: 'VS Code Dark' },
  { value: 'dracula', label: 'Dracula' },
  { value: 'material-dark', label: 'Material Dark' },
  { value: 'nord', label: 'Nord' },
] as const

export function DashboardSettings() {
  const { data: prefs } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const { enabled: simplifiedWorkflow, setEnabled: setSimplifiedWorkflow } = useSimplifiedWorkflow()
  const { data: globalSettings } = useGlobalSettings()
  const updateGlobalSettings = useUpdateGlobalSettings()

  const editorTheme = globalSettings?.editor_theme ?? 'github-dark'
  const showKpiBar = prefs?.dashboard?.showKpiBar ?? true
  const showStatsWidgets = prefs?.dashboard?.showStatsWidgets ?? false
  const optimizedLoading = prefs?.dashboard?.optimizedLoading ?? true
  const showContainerStats = prefs?.dashboard?.showContainerStats ?? false

  const handleToggleKpiBar = (checked: boolean) => {
    updatePreferences.mutate({
      dashboard: {
        ...prefs?.dashboard,
        showKpiBar: checked
      }
    })
    toast.success(checked ? 'KPI bar enabled' : 'KPI bar disabled')
  }

  const handleToggleStatsWidgets = (checked: boolean) => {
    updatePreferences.mutate({
      dashboard: {
        ...prefs?.dashboard,
        showStatsWidgets: checked
      }
    })
    toast.success(checked ? 'Stats widgets enabled' : 'Stats widgets disabled')
  }

  const handleToggleOptimizedLoading = (checked: boolean) => {
    updatePreferences.mutate({
      dashboard: {
        ...prefs?.dashboard,
        optimizedLoading: checked
      }
    })
    toast.success(checked ? 'Optimized loading enabled' : 'Optimized loading disabled')
  }

  const handleToggleContainerStats = (checked: boolean) => {
    updatePreferences.mutate({
      dashboard: {
        ...prefs?.dashboard,
        showContainerStats: checked
      }
    })
    toast.success(checked ? 'Container statistics enabled' : 'Container statistics disabled')
  }

  const handleToggleSimplifiedWorkflow = (checked: boolean) => {
    setSimplifiedWorkflow(checked)
    toast.success(checked ? 'Simplified workflow enabled - drawers skipped' : 'Simplified workflow disabled - drawers shown')
  }

  const handleEditorThemeChange = async (theme: string) => {
    try {
      await updateGlobalSettings.mutateAsync({ editor_theme: theme })
      toast.success(`Editor theme changed to ${EDITOR_THEMES.find(t => t.value === theme)?.label}`)
    } catch {
      toast.error('Failed to update editor theme')
    }
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
          <ToggleSwitch
            id="show-container-stats"
            label="Show CPU/RAM statistics per container"
            description="Display CPU usage and memory consumption for each running container in the expanded view"
            checked={showContainerStats}
            onChange={handleToggleContainerStats}
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

      {/* Editor */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Editor</h3>
          <p className="text-xs text-gray-400 mt-1">
            Customize the code editor appearance for stack and container configurations
          </p>
        </div>
        <div className="space-y-4">
          <div>
            <label htmlFor="editor-theme" className="block text-sm font-medium text-gray-300 mb-2">
              Editor Theme
            </label>
            <Select value={editorTheme} onValueChange={handleEditorThemeChange}>
              <SelectTrigger id="editor-theme" className="w-full">
                <SelectValue>
                  {EDITOR_THEMES.find(t => t.value === editorTheme)?.label}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {EDITOR_THEMES.map((theme) => (
                  <SelectItem key={theme.value} value={theme.value}>
                    {theme.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="mt-1 text-xs text-gray-400">
              Color theme for YAML and JSON editing in stack deployments
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
