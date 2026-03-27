/**
 * ContainerOverviewTab - Overview content for Container Drawer
 *
 * Displays:
 * - Identity (name, image, host, status)
 * - Mini sparklines (CPU, Memory, Network)
 * - Info (uptime, created, restart policy)
 * - Ports and Labels
 * - Action buttons (Stop/Restart)
 */

import { useEffect, useState, useMemo } from 'react'
import { useAuth } from '@/features/auth/AuthContext'
import { Circle } from 'lucide-react'
import { useContainer, useContainerSparklines } from '@/lib/stats/StatsProvider'
import { StatsCharts } from '@/lib/charts/StatsCharts'
import { StatsTimeRangeSelector } from '../StatsTimeRangeSelector'
import { useStatsHistory, type TimeRange } from '../../hooks/useStatsHistory'
import { VIEWS, LIVE_TIME_WINDOW, DEFAULT_HIST_TIME_WINDOW } from '@/lib/statsConfig'
import { TagEditor } from './TagEditor'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import { formatBytes, formatNetworkRate } from '@/lib/utils/formatting'

interface ContainerOverviewTabProps {
  containerId: string
  actionButtons?: React.ReactNode
}

export function ContainerOverviewTab({ containerId, actionButtons }: ContainerOverviewTabProps) {
  const { hasCapability } = useAuth()
  const canOperate = hasCapability('containers.operate')
  const container = useContainer(containerId)
  const sparklines = useContainerSparklines(containerId)
  const [uptime, setUptime] = useState<string>('')
  const [autoRestart, setAutoRestart] = useState(false)
  const [desiredState, setDesiredState] = useState<'should_run' | 'on_demand' | 'unspecified'>('unspecified')
  const [timeRange, setTimeRange] = useState<TimeRange>('live')

  const hostId = container?.host_id || ''
  const shortId = containerId.includes(':') ? containerId.split(':')[1] : containerId
  const { data: historyData } = useStatsHistory(hostId, shortId, timeRange)
  const hist = useMemo(() => {
    const d = historyData?.data ?? []
    return {
      cpu: d.map((p) => p.cpu),
      mem: d.map((p) => p.mem),
      net: d.map((p) => p.net),
      timestamps: d.map((p) => p.t / 1000),
    }
  }, [historyData])
  const histTimeWindow = VIEWS.find(v => v.name === timeRange)?.seconds

  useEffect(() => {
    if (container) {
      setAutoRestart(container.auto_restart ?? false)

      const validStates: Array<'should_run' | 'on_demand' | 'unspecified'> = ['should_run', 'on_demand', 'unspecified']
      const containerState = container.desired_state as 'should_run' | 'on_demand' | 'unspecified' | undefined
      const newState = containerState && validStates.includes(containerState) ? containerState : 'unspecified'
      setDesiredState(newState)
    }
  }, [containerId, container?.auto_restart, container?.desired_state])

  useEffect(() => {
    if (!container?.created) return

    const updateUptime = () => {
      const startTime = new Date(container.started_at || container.created)
      const now = new Date()
      const diff = now.getTime() - startTime.getTime()

      const hours = Math.floor(diff / (1000 * 60 * 60))
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))

      if (hours > 24) {
        const days = Math.floor(hours / 24)
        setUptime(`${days}d ${hours % 24}h`)
      } else if (hours > 0) {
        setUptime(`${hours}h ${minutes}m`)
      } else {
        setUptime(`${minutes}m`)
      }
    }

    updateUptime()

    if (container.state !== 'running') return

    const interval = setInterval(updateUptime, 60000)
    return () => clearInterval(interval)
  }, [container?.created, container?.started_at, container?.state])

  if (!container) {
    return (
      <div className="p-4">
        <div className="text-muted-foreground text-sm">Loading container details...</div>
      </div>
    )
  }

  const getStatusColor = (state: string) => {
    switch (state.toLowerCase()) {
      case 'running':
        return 'text-success fill-success'
      case 'paused':
        return 'text-warning fill-warning'
      case 'restarting':
        return 'text-info fill-info'
      case 'exited':
      case 'dead':
        return 'text-danger fill-danger'
      default:
        return 'text-muted-foreground fill-muted-foreground'
    }
  }

  const handleAutoRestartToggle = async (checked: boolean) => {
    if (!container) return

    setAutoRestart(checked)

    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${container.id}/auto-restart`, {
        enabled: checked,
        container_name: container.name
      })
      toast.success(`Auto-restart ${checked ? 'enabled' : 'disabled'}`)
    } catch (error) {
      debug.error('ContainerOverviewTab', 'Error toggling auto-restart:', error)
      toast.error(`Failed to update auto-restart: ${error instanceof Error ? error.message : 'Unknown error'}`)
      setAutoRestart(!checked)
    }
  }

  const handleDesiredStateChange = async (state: 'should_run' | 'on_demand' | 'unspecified') => {
    if (!container) return

    const previousState = desiredState
    setDesiredState(state)

    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${container.id}/desired-state`, {
        desired_state: state,
        container_name: container.name
      })
      const stateLabel = state === 'should_run' ? 'Should Run' : state === 'on_demand' ? 'On-Demand' : 'Unspecified'
      toast.success(`Desired state set to ${stateLabel}`)
    } catch (error) {
      debug.error('ContainerOverviewTab', 'Error setting desired state:', error)
      toast.error(`Failed to update desired state: ${error instanceof Error ? error.message : 'Unknown error'}`)
      setDesiredState(previousState)
    }
  }

  return (
    <div className="p-4 space-y-6">
      {/* Container Name and Status */}
      <div>
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2">
            <Circle className={`w-3 h-3 ${getStatusColor(container.state)}`} />
            <h3 className="text-lg font-semibold text-foreground">{container.name}</h3>
          </div>
          {/* Action Buttons */}
          {actionButtons && (
            <div className="flex gap-2">
              {actionButtons}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-sm px-2 py-1 rounded ${
            container.state === 'running'
              ? 'bg-success/10 text-success'
              : 'bg-muted text-muted-foreground'
          }`}>
            {container.state.charAt(0).toUpperCase() + container.state.slice(1)}
          </span>
        </div>
      </div>

      {/* Identity Section */}
      <div className="space-y-3">
        <div className="flex flex-col sm:flex-row sm:justify-between gap-1 sm:gap-2 text-sm">
          <span className="text-muted-foreground">Host</span>
          <span className="text-foreground break-all">{container.host_name || '-'}</span>
        </div>

        <div className="flex flex-col sm:flex-row sm:justify-between gap-1 sm:gap-2 text-sm">
          <span className="text-muted-foreground">Image</span>
          <span className="text-foreground font-mono text-xs sm:text-sm break-all">{container.image || '-'}</span>
        </div>

        {/* Tags Row */}
        <div className="pt-1">
          <TagEditor
            tags={container.tags || []}
            containerId={container.id}
            hostId={container.host_id}
          />
        </div>
      </div>

      {/* Controls Section */}
      <fieldset disabled={!canOperate} className="border-t border-border pt-4 space-y-4 disabled:opacity-60">
        <h4 className="text-sm font-medium text-foreground mb-3">Controls</h4>

        {/* Auto-Restart Checkbox */}
        <div className="flex items-start gap-2">
          <input
            type="checkbox"
            id="auto-restart"
            checked={autoRestart}
            onChange={(e) => handleAutoRestartToggle(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-border text-primary focus:ring-primary"
          />
          <div className="flex-1 space-y-0.5">
            <label htmlFor="auto-restart" className="text-sm font-medium cursor-pointer">
              Auto-restart when stopped
            </label>
            <p className="text-xs text-muted-foreground">
              DockMon will automatically restart this container if it stops or crashes
            </p>
          </div>
        </div>

        {/* Desired State Selector */}
        <div className="space-y-2">
          <label className="text-sm font-medium">Desired State</label>
          <p className="text-xs text-muted-foreground">
            Controls how DockMon treats a stopped container. "On-Demand" containers won't trigger warnings when stopped.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => handleDesiredStateChange('should_run')}
              className={`flex-1 px-3 py-2 text-sm rounded border transition-colors ${
                desiredState === 'should_run'
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'border-border hover:bg-muted'
              }`}
            >
              Should Run
            </button>
            <button
              onClick={() => handleDesiredStateChange('on_demand')}
              className={`flex-1 px-3 py-2 text-sm rounded border transition-colors ${
                desiredState === 'on_demand'
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'border-border hover:bg-muted'
              }`}
            >
              On-Demand
            </button>
            <button
              onClick={() => handleDesiredStateChange('unspecified')}
              className={`flex-1 px-3 py-2 text-sm rounded border transition-colors ${
                desiredState === 'unspecified'
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'border-border hover:bg-muted'
              }`}
            >
              Unspecified
            </button>
          </div>
        </div>
      </fieldset>

      {/* Information Section */}
      <div className="border-t border-border pt-4 space-y-2">
        <h4 className="text-sm font-medium text-foreground mb-3">Information</h4>

        <div className="flex flex-col sm:flex-row sm:justify-between gap-1 sm:gap-2 text-sm">
          <span className="text-muted-foreground">Created</span>
          <span className="text-foreground">
            {container.created
              ? new Date(container.created).toLocaleDateString('en-US', {
                  month: 'long',
                  day: 'numeric',
                  year: 'numeric'
                })
              : '-'
            }
          </span>
        </div>

        <div className="flex flex-col sm:flex-row sm:justify-between gap-1 sm:gap-2 text-sm">
          <span className="text-muted-foreground">Uptime</span>
          <span className="text-foreground">{uptime || '-'}</span>
        </div>

        {/* Ports */}
        <div className="space-y-1">
          <span className="text-sm text-muted-foreground">Ports</span>
          <div className="text-sm text-foreground font-mono bg-muted/20 p-2 rounded">
            {container.ports && container.ports.length > 0
              ? container.ports.join(', ')
              : <span className="text-muted-foreground">No ports exposed</span>
            }
          </div>
        </div>
      </div>

      {/* Stats Section */}
      <div className="border-t border-border pt-4 space-y-4">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-medium text-foreground">Performance</h4>
          <StatsTimeRangeSelector value={timeRange} onChange={setTimeRange} />
        </div>

        {timeRange === 'live' ? (
          <StatsCharts
            cpu={sparklines?.cpu ?? []}
            mem={sparklines?.mem ?? []}
            net={sparklines?.net ?? []}
            timestamps={sparklines?.timestamps ?? []}
            timeWindow={LIVE_TIME_WINDOW}
            cpuValue={container.cpu_percent != null ? `${container.cpu_percent.toFixed(1)}%` : undefined}
            memValue={container.memory_usage ? formatBytes(container.memory_usage) : undefined}
            netValue={container.net_bytes_per_sec != null ? formatNetworkRate(container.net_bytes_per_sec) : undefined}
          />
        ) : (
          <StatsCharts
            cpu={hist.cpu}
            mem={hist.mem}
            net={hist.net}
            timestamps={hist.timestamps}
            timeWindow={histTimeWindow ?? DEFAULT_HIST_TIME_WINDOW}
            footer={historyData ? `${historyData.points} data points (${historyData.resolution} resolution)` : undefined}
          />
        )}
      </div>
    </div>
  )
}
