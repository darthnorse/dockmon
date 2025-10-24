/**
 * KPI Bar Component
 * Displays key performance indicators at the top of the dashboard
 * - Fixed position during scroll
 * - 5 metric cards: Hosts, Containers, Running, Alerts, Updates
 * - Clickable cards with navigation
 * - Responsive grid layout
 */

import { useNavigate } from 'react-router-dom'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import { useStatsContext } from '@/lib/stats/StatsProvider'
import { useAlertStats } from '@/features/alerts/hooks/useAlerts'
import { useUpdatesSummary } from '@/features/containers/hooks/useContainerUpdates'
import { Server, Box, Play, AlertTriangle, RefreshCw } from 'lucide-react'

interface KpiCardProps {
  icon: React.ReactNode
  label: string
  value: number | string
  subtitle?: string
  onClick?: () => void
  variant?: 'default' | 'success' | 'warning' | 'error'
  'data-testid'?: string
}

function KpiCard({ icon, label, value, subtitle, onClick, variant = 'default', 'data-testid': dataTestId }: KpiCardProps) {
  const variantStyles = {
    default: 'bg-surface border-border hover:border-accent/50',
    success: 'bg-surface border-green-500/30 hover:border-green-500/50',
    warning: 'bg-surface border-yellow-500/30 hover:border-yellow-500/50',
    error: 'bg-surface border-red-500/30 hover:border-red-500/50',
  }

  return (
    <button
      onClick={onClick}
      className={`
        ${variantStyles[variant]}
        border rounded-lg p-4 transition-all
        ${onClick ? 'cursor-pointer hover:shadow-md' : 'cursor-default'}
        flex flex-col gap-2 text-left
      `}
      data-testid={dataTestId}
    >
      <div className="flex items-center gap-2 text-muted-foreground">
        {icon}
        <span className="text-sm font-medium">{label}</span>
      </div>
      <div className="text-2xl font-bold">{value}</div>
      {subtitle && <div className="text-sm text-muted-foreground">{subtitle}</div>}
    </button>
  )
}

export function KpiBar() {
  const navigate = useNavigate()
  const { data: hosts } = useHosts()
  const { containerStats } = useStatsContext()
  const { data: alertStats } = useAlertStats()
  const { data: updatesSummary } = useUpdatesSummary()

  // Calculate metrics
  const totalHosts = hosts?.length || 0
  const onlineHosts = hosts?.filter(h => h.status === 'online').length || 0
  const offlineHosts = totalHosts - onlineHosts

  // Calculate container counts from containerStats Map
  let totalContainers = 0
  let runningContainers = 0
  containerStats.forEach((container) => {
    totalContainers++
    if (container.state === 'running') {
      runningContainers++
    }
  })
  const stoppedContainers = totalContainers - runningContainers

  // Get open alerts count (snoozed will become open when they wake up)
  const activeAlerts = alertStats?.by_state.open || 0

  // Get real updates count from backend
  const pendingUpdates = updatesSummary?.total_updates || 0

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4" data-testid="kpi-bar">
      {/* Hosts */}
      <KpiCard
        icon={<Server className="w-4 h-4" />}
        label="Hosts"
        value={totalHosts}
        subtitle={`${onlineHosts} online • ${offlineHosts} offline`}
        onClick={() => navigate('/hosts')}
        variant={onlineHosts === totalHosts ? 'success' : 'default'}
        data-testid="kpi-total-hosts"
      />

      {/* Total Containers */}
      <KpiCard
        icon={<Box className="w-4 h-4" />}
        label="Containers"
        value={totalContainers}
        subtitle={`${runningContainers} running • ${stoppedContainers} stopped`}
        onClick={() => navigate('/containers')}
        data-testid="kpi-total-containers"
      />

      {/* Running Containers */}
      <KpiCard
        icon={<Play className="w-4 h-4" />}
        label="Running"
        value={runningContainers}
        subtitle={totalContainers > 0 ? `${Math.round((runningContainers / totalContainers) * 100)}% of total` : ''}
        onClick={() => navigate('/containers?state=running')}
        variant={runningContainers > 0 ? 'success' : 'default'}
        data-testid="kpi-running-containers"
      />

      {/* Alerts */}
      <KpiCard
        icon={<AlertTriangle className="w-4 h-4" />}
        label="Alerts"
        value={activeAlerts}
        subtitle={activeAlerts > 0 ? 'Requires attention' : 'All clear'}
        onClick={() => navigate('/alerts')}
        variant={activeAlerts > 0 ? 'warning' : 'success'}
      />

      {/* Updates */}
      <KpiCard
        icon={<RefreshCw className="w-4 h-4" />}
        label="Updates"
        value={pendingUpdates}
        subtitle={pendingUpdates > 0 ? 'Updates available' : 'Up to date'}
        onClick={() => navigate('/containers?updates=true')}
        variant={pendingUpdates > 0 ? 'warning' : 'success'}
      />
    </div>
  )
}
