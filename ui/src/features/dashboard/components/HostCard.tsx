/**
 * HostCard - Standard Mode Host Card Component
 * Phase 4c
 *
 * FEATURES:
 * - Host name and status indicator
 * - CPU/Memory/Network sparklines with current values
 * - Top 3 containers by CPU usage
 * - Footer badges (container count, updates, alerts)
 * - Hover effects and click navigation
 *
 * USAGE:
 * <HostCard host={hostData} />
 */

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Circle, MoreVertical, Container, ChevronDown, Info, Edit, ChevronsUp } from 'lucide-react'
import { ResponsiveMiniChart } from '@/lib/charts/ResponsiveMiniChart'
import { TagChip } from '@/components/TagChip'
import { DropdownMenu, DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { useUserPreferences, useUpdatePreferences, useSimplifiedWorkflow } from '@/lib/hooks/useUserPreferences'
import { useContainerModal } from '@/providers'
import { makeCompositeKeyFrom } from '@/lib/utils/containerKeys'

export interface HostCardData {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'error'
  tags?: string[]

  // Current stats
  stats?: {
    cpu_percent: number
    mem_percent: number
    mem_used_gb: number
    mem_total_gb: number
    net_bytes_per_sec: number
  }

  // Historical data for sparklines (last 30-40 data points)
  sparklines?: {
    cpu: number[]
    mem: number[]
    net: number[]
  }

  // Container summary
  containers?: {
    total: number
    running: number
    stopped: number
    top?: Array<{
      id: string
      name: string
      state: string
      cpu_percent: number
      memory_percent?: number
    }>
  }

  // Alerts & updates
  alerts?: {
    open: number
    snoozed: number
  }
  updates_available?: number
}

interface HostCardProps {
  host: HostCardData
  onHostClick?: (hostId: string) => void
  onViewDetails?: (hostId: string) => void
  onEditHost?: (hostId: string) => void
}

/**
 * Format bytes per second to human-readable format
 */
function formatNetworkSpeed(bytesPerSec: number): string {
  if (bytesPerSec < 1024) return `${bytesPerSec.toFixed(0)} B/s`
  if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`
  return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`
}

/**
 * Get status indicator color
 */
function getStatusColor(status: string): string {
  switch (status) {
    case 'online':
      return 'text-success fill-success'
    case 'offline':
      return 'text-muted-foreground fill-muted-foreground'
    case 'error':
      return 'text-danger fill-danger'
    default:
      return 'text-muted-foreground fill-muted-foreground'
  }
}

/**
 * Get container state color
 */
function getStateColor(state: string): string {
  switch (state.toLowerCase()) {
    case 'running':
      return 'text-success'
    case 'exited':
    case 'stopped':
      return 'text-muted-foreground'
    case 'paused':
      return 'text-warning'
    case 'restarting':
      return 'text-info'
    default:
      return 'text-muted-foreground'
  }
}

type ContainerSortKey = 'name' | 'state' | 'cpu' | 'memory'

export function HostCard({ host, onHostClick, onViewDetails, onEditHost }: HostCardProps) {
  const navigate = useNavigate()
  const { data: prefs } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const { enabled: simplifiedWorkflow } = useSimplifiedWorkflow()
  const { openModal } = useContainerModal()
  const [collapsed, setCollapsed] = useState(false)

  // Initialize sort key from preferences, fallback to 'cpu'
  const [sortKey, setSortKey] = useState<ContainerSortKey>(() => {
    const savedSort = prefs?.hostContainerSorts?.[host.id]
    return (savedSort as ContainerSortKey) || 'cpu'
  })

  // Update local state when preferences change (e.g., loaded from server)
  useEffect(() => {
    const savedSort = prefs?.hostContainerSorts?.[host.id]
    if (savedSort) {
      setSortKey(savedSort as ContainerSortKey)
    }
  }, [prefs?.hostContainerSorts, host.id])

  const hasStats = host.stats && host.sparklines

  // Fix #7: Check if sparklines have valid data (not just priming zeros)
  // Network sparklines start at 0 during priming - wait for at least 2 valid readings
  const hasValidNetworkData = host.sparklines
    ? host.sparklines.net.filter(v => v > 0).length >= 2
    : false

  const hasContainers = host.containers && host.containers.total > 0
  const containers = host.containers?.top || []

  // Sort containers based on selected key
  const sortedContainers = [...containers].sort((a, b) => {
    switch (sortKey) {
      case 'name':
        return a.name.localeCompare(b.name)
      case 'state':
        // Running first, then alphabetically
        if (a.state === 'running' && b.state !== 'running') return -1
        if (a.state !== 'running' && b.state === 'running') return 1
        return a.name.localeCompare(b.name)
      case 'cpu':
        return (b.cpu_percent || 0) - (a.cpu_percent || 0)
      case 'memory':
        return (b.memory_percent || 0) - (a.memory_percent || 0)
      default:
        return 0
    }
  })

  const topContainers = sortedContainers.slice(0, 3)

  const getSortLabel = (key: ContainerSortKey) => {
    switch (key) {
      case 'name':
        return 'Name (A–Z)'
      case 'state':
        return 'State (Running first)'
      case 'cpu':
        return 'CPU (High to Low)'
      case 'memory':
        return 'Memory (High to Low)'
      default:
        return 'Sort by'
    }
  }

  // Handle sort change and save to preferences
  const handleSortChange = (newSort: ContainerSortKey) => {
    setSortKey(newSort)
    updatePreferences.mutate({
      hostContainerSorts: {
        ...(prefs?.hostContainerSorts || {}),
        [host.id]: newSort,
      },
    })
  }

  // Handle click based on simplified workflow preference
  const handleHostClick = () => {
    if (simplifiedWorkflow) {
      onViewDetails?.(host.id)
    } else {
      onHostClick?.(host.id)
    }
  }

  return (
    <div
      className="bg-surface border border-border rounded-lg p-4 hover:shadow-lg hover:border-accent/50 transition-all cursor-pointer"
      onClick={handleHostClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleHostClick()
        }
      }}
      aria-label={`Host ${host.name}, ${host.status}`}
    >
      {/* Header - Name, Status, Menu */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Circle className={`w-3 h-3 ${getStatusColor(host.status)}`} />
          <h3 className="text-base font-semibold text-foreground truncate">{host.name}</h3>
        </div>
        <div className="relative z-20" onClick={(e) => e.stopPropagation()}>
          <DropdownMenu
            trigger={
              <button
                className="text-muted-foreground hover:text-foreground p-1 -mr-1"
                aria-label="Host actions"
              >
                <MoreVertical className="w-4 h-4" />
              </button>
            }
            align="end"
          >
          {onViewDetails && (
            <DropdownMenuItem onClick={() => onViewDetails(host.id)} icon={<Info className="h-3.5 w-3.5" />}>
              View Host Details
            </DropdownMenuItem>
          )}
          {onEditHost && (
            <DropdownMenuItem onClick={() => onEditHost(host.id)} icon={<Edit className="h-3.5 w-3.5" />}>
              Edit Host
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={() => setCollapsed(!collapsed)} icon={<ChevronsUp className="h-3.5 w-3.5" />}>
            {collapsed ? 'Expand' : 'Collapse'} Containers
          </DropdownMenuItem>
        </DropdownMenu>
        </div>
      </div>

      {/* Tags */}
      {host.tags && host.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {host.tags.slice(0, 3).map((tag) => (
            <TagChip key={tag} tag={tag} size="sm" />
          ))}
          {host.tags.length > 3 && (
            <span className="text-xs text-muted-foreground">+{host.tags.length - 3}</span>
          )}
        </div>
      )}

      {/* Stats with Sparklines */}
      {hasStats ? (
        <div className="space-y-2 mb-3">
          {/* CPU */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-8">CPU:</span>
            <div className="flex-1">
              <ResponsiveMiniChart
                data={host.sparklines!.cpu}
                color="cpu"
                height={32}
                label={`${host.name} CPU usage`}
              />
            </div>
            <span className="text-xs font-mono text-foreground w-12 text-right">
              {host.stats!.cpu_percent.toFixed(1)}%
            </span>
          </div>

          {/* Memory */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-8">Mem:</span>
            <div className="flex-1">
              <ResponsiveMiniChart
                data={host.sparklines!.mem}
                color="memory"
                height={32}
                label={`${host.name} Memory usage`}
              />
            </div>
            <span className="text-xs font-mono text-foreground w-12 text-right">
              {host.stats!.mem_percent.toFixed(1)}%
            </span>
          </div>

          {/* Network */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-8">Net:</span>
            <div className="flex-1">
              {hasValidNetworkData ? (
                <ResponsiveMiniChart
                  data={host.sparklines!.net}
                  color="network"
                  height={32}
                  label={`${host.name} Network I/O`}
                />
              ) : (
                <div className="h-[32px] flex items-center justify-center text-xs text-muted-foreground">
                  —
                </div>
              )}
            </div>
            <span className="text-xs font-mono text-foreground w-20 text-right">
              {hasValidNetworkData ? formatNetworkSpeed(host.stats!.net_bytes_per_sec) : '—'}
            </span>
          </div>
        </div>
      ) : (
        <div className="text-xs text-muted-foreground mb-3">No stats available</div>
      )}

      {/* Top Containers */}
      {!collapsed && topContainers.length > 0 && (
        <div className="border-t border-border pt-3 mb-3">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs text-muted-foreground">Top Containers:</div>
            <DropdownMenu
              trigger={
                <button className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
                  <span>{getSortLabel(sortKey)}</span>
                  <ChevronDown className="h-3 w-3" />
                </button>
              }
              align="end"
            >
              <DropdownMenuItem onClick={() => handleSortChange('cpu')}>
                CPU (High to Low)
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleSortChange('state')}>
                State (Running first)
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleSortChange('name')}>
                Name (A–Z)
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleSortChange('memory')}>
                Memory (High to Low)
              </DropdownMenuItem>
            </DropdownMenu>
          </div>
          <div className="space-y-1">
            {topContainers.map((container) => (
              <div
                key={container.id}
                className="flex items-center justify-between text-xs"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <button
                    className="text-foreground truncate hover:text-primary transition-colors text-left"
                    onClick={() => openModal(makeCompositeKeyFrom(host.id, container.id), 'info')}
                  >
                    {container.name}
                  </button>
                  <span className={`text-xs ${getStateColor(container.state)}`}>
                    [{container.state}]
                  </span>
                </div>
                {prefs?.dashboard?.showContainerStats && container.state === 'running' && (
                  <div className="flex items-center gap-1 flex-shrink-0 text-muted-foreground font-mono text-xs whitespace-nowrap">
                    <span>{container.cpu_percent.toFixed(1)}%</span>
                    <span>/</span>
                    <span>
                      {container.memory_percent !== undefined ? `${container.memory_percent.toFixed(0)}MB` : '—'}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer - Badges */}
      <div className="flex items-center gap-4 text-xs border-t border-border pt-3">
        {/* Container count */}
        {hasContainers && (
          <div className="flex items-center gap-1 text-muted-foreground">
            <Container className="w-3 h-3" />
            <span>
              {host.containers!.running} / {host.containers!.total}
            </span>
          </div>
        )}

        {/* Updates available - clickable, navigates to containers filtered by this host */}
        {host.updates_available && host.updates_available > 0 && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              navigate(`/containers?host=${host.id}`)
            }}
            className="flex items-center gap-1 text-info hover:text-info/80 transition-colors"
            title="View containers with updates on this host"
          >
            <span>🔄</span>
            <span>{host.updates_available}</span>
          </button>
        )}

        {/* Alerts */}
        {host.alerts && (host.alerts.open > 0 || host.alerts.snoozed > 0) && (
          <div className="flex items-center gap-1 text-warning">
            <span>⚠️</span>
            <span>
              {host.alerts.open}
              {host.alerts.snoozed > 0 && ` (+${host.alerts.snoozed})`}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
