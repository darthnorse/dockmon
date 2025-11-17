/**
 * ExpandedHostCard - Expanded Mode Host Card Component
 * Phase 4d
 *
 * FEATURES:
 * - Same header and sparklines as Standard mode
 * - Expanded container list (up to 24, virtualized) instead of just top 3
 * - Per-container controls (start/stop toggle)
 * - Footer with container count badge
 * - Click container row → opens Container Drawer (Phase 5+)
 *
 * USAGE:
 * <ExpandedHostCard host={hostData} />
 */

import {
  Circle,
  MoreVertical,
  Container,
  Info,
  Edit,
  ChevronsUp,
  ChevronDown,
  ArrowUpDown,
  Play,
  Square,
  RotateCcw,
  ScrollText,
  ExternalLink,
} from 'lucide-react'
import { ResponsiveMiniChart } from '@/lib/charts/ResponsiveMiniChart'
import { TagChip } from '@/components/TagChip'
import { useState, useEffect } from 'react'
import { DropdownMenu, DropdownMenuItem, DropdownMenuSeparator } from '@/components/ui/dropdown-menu'
import { useUserPreferences, useUpdatePreferences, useSimplifiedWorkflow } from '@/lib/hooks/useUserPreferences'
import { useContainerActions } from '@/features/containers/hooks/useContainerActions'
import { useContainerModal } from '@/providers'
import { makeCompositeKeyFrom } from '@/lib/utils/containerKeys'
import { debug } from '@/lib/debug'

export interface ExpandedHostData {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'error'
  tags?: string[]

  // Current stats for sparklines
  stats?: {
    cpu_percent: number
    mem_percent: number
    mem_used_gb: number
    mem_total_gb: number
    net_bytes_per_sec: number
  }

  // Sparklines
  sparklines?: {
    cpu: number[]
    mem: number[]
    net: number[]
  }

  // Container data
  containers?: {
    total: number
    running: number
    stopped: number
    items: Array<{
      id: string
      short_id: string
      name: string
      state: string
      status: string
      cpu_percent: number | null
      memory_percent: number | null
      network_rx: number | null
      network_tx: number | null
      web_ui_url?: string | null | undefined
    }>
  }

  // Footer data
  alerts?: {
    open: number
    snoozed: number
  }
  updates_available?: number
}

interface ExpandedHostCardProps {
  host: ExpandedHostData
  cardRef?: React.RefObject<HTMLDivElement>
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
  if (bytesPerSec < 1024 * 1024 * 1024) return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`
  return `${(bytesPerSec / (1024 * 1024 * 1024)).toFixed(2)} GB/s`
}

/**
 * Get status dot color
 */
function getStatusColor(status: string): string {
  switch (status) {
    case 'online':
      return 'fill-success'
    case 'offline':
      return 'fill-muted-foreground'
    case 'error':
      return 'fill-destructive'
    default:
      return 'fill-muted-foreground'
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

type ContainerSortKey = 'name' | 'state' | 'cpu' | 'memory' | 'start_time'

export function ExpandedHostCard({ host, cardRef, onHostClick, onViewDetails, onEditHost }: ExpandedHostCardProps) {
  const { data: prefs } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const { enabled: simplifiedWorkflow } = useSimplifiedWorkflow()
  const [isCollapsed, setIsCollapsed] = useState(false)
  const { executeAction } = useContainerActions()
  const { openModal } = useContainerModal()

  // Initialize sort key from preferences, fallback to 'state'
  const [sortKey, setSortKey] = useState<ContainerSortKey>(() => {
    const savedSort = prefs?.hostContainerSorts?.[host.id]
    return (savedSort as ContainerSortKey) || 'state'
  })

  // Update local state when preferences change (e.g., loaded from server)
  useEffect(() => {
    const savedSort = prefs?.hostContainerSorts?.[host.id]
    if (savedSort) {
      setSortKey(savedSort as ContainerSortKey)
    }
  }, [prefs?.hostContainerSorts, host.id])

  const hasStats = host.stats && host.sparklines
  // Wait for at least 2 data points (4 seconds), then always show even if zero
  const hasValidNetworkData = host.sparklines
    ? host.sparklines.net.length >= 2
    : false

  const hasContainers = host.containers && host.containers.total > 0
  const containers = host.containers?.items || []

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
      case 'start_time':
        // TODO: Implement once we have start_time in container data
        return a.name.localeCompare(b.name)
      default:
        return 0
    }
  })

  const displayContainers = sortedContainers

  const handleContainerClick = (containerId: string) => {
    // Open container modal on info tab
    openModal(makeCompositeKeyFrom(host.id, containerId), 'info')
  }

  const handleContainerAction = (containerId: string, action: string) => {
    if (action === 'start' || action === 'stop' || action === 'restart') {
      // Execute container lifecycle action
      executeAction({
        type: action as 'start' | 'stop' | 'restart',
        host_id: host.id,
        container_id: containerId, // Short 12-char ID
      })
    } else if (action === 'logs') {
      // Open global modal on logs tab - no navigation, stays in dashboard context
      // Dashboard container items don't have host_id, so use makeCompositeKeyFrom
      openModal(makeCompositeKeyFrom(host.id, containerId), 'logs')
    } else {
      // Unimplemented actions (silence, hide, pin)
      debug.log('ExpandedHostCard', `${action} container:`, containerId)
    }
  }

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
      case 'start_time':
        return 'Start Time (Newest first)'
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

  // Handle card click based on simplified workflow preference
  const handleCardClick = () => {
    if (simplifiedWorkflow) {
      onViewDetails?.(host.id)
    } else {
      onHostClick?.(host.id)
    }
  }

  return (
    <div
      ref={cardRef}
      className="bg-surface border border-border rounded-lg p-4 hover:shadow-lg hover:border-accent/50 transition-all h-full flex flex-col cursor-pointer"
      onClick={handleCardClick}
      aria-label={`Host ${host.name}, ${host.status}`}
    >
      {/* Header - Name, Status, Menu (drag handle area) */}
      <div className="flex items-start justify-between mb-3 host-card-drag-handle-content">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Circle className={`w-3 h-3 ${getStatusColor(host.status)}`} />
          <h3 className="text-base font-semibold text-foreground truncate">
            {host.name}
          </h3>
        </div>
        <div onClick={(e) => e.stopPropagation()} className="relative z-20">
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
            <DropdownMenuItem
              onClick={() => setIsCollapsed(!isCollapsed)}
              icon={<ChevronsUp className="h-3.5 w-3.5" />}
            >
              {isCollapsed ? 'Expand' : 'Collapse'} Containers
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

      {/* Stats with Sparklines (same as Standard mode) */}
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

      {/* Expanded Container List - Multi-column responsive grid */}
      {displayContainers.length > 0 && !isCollapsed && (
        <div className="border-t border-border pt-3 flex-1 flex flex-col min-h-0">
          {/* Container Sort Control */}
          <div className="flex items-center justify-between mb-2 px-2 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
            <span className="text-xs text-muted-foreground">
              {displayContainers.length} container{displayContainers.length !== 1 ? 's' : ''}
            </span>
            <DropdownMenu
              trigger={
                <button className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                  <ArrowUpDown className="w-3 h-3" />
                  <span>{getSortLabel(sortKey)}</span>
                  <ChevronDown className="w-3 h-3" />
                </button>
              }
              align="end"
            >
              <DropdownMenuItem onClick={() => handleSortChange('state')}>
                State (Running first)
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleSortChange('name')}>Name (A–Z)</DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleSortChange('cpu')}>
                CPU (High to Low)
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleSortChange('memory')}>
                Memory (High to Low)
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleSortChange('start_time')} disabled>
                Start Time (Newest first)
              </DropdownMenuItem>
            </DropdownMenu>
          </div>

          {/* Multi-column container grid - responsive columns with scroll */}
          <div
            className="overflow-auto flex-1"
            style={{
              overscrollBehavior: 'contain',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                gap: '0.25rem',
                gridAutoRows: 'min-content',
                width: '100%',
              }}
            >
              {displayContainers.map((container) => (
                <div
                  key={container.id}
                  className="px-2 hover:bg-accent/10 cursor-pointer flex items-center gap-2"
                  style={{ height: '36px' }}
                  onClick={(e) => {
                    e.stopPropagation()
                    handleContainerClick(container.id)
                  }}
                >
                    {/* Status Dot */}
                    <Circle className={`w-2 h-2 ${getStateColor(container.state)} flex-shrink-0`} />

                    {/* Container Name */}
                    <span className="text-sm text-foreground hover:text-primary transition-colors truncate flex-1 min-w-0">
                      {container.name}
                    </span>

                    {/* State Badge */}
                    <span
                      className={`text-xs px-2 py-0.5 rounded flex-shrink-0 ${
                        container.state === 'running'
                          ? 'bg-success/10 text-success'
                          : 'bg-muted text-muted-foreground'
                      }`}
                    >
                      {container.state.toUpperCase()}
                    </span>

                    {/* Container Stats (CPU/RAM) - only for running containers when enabled */}
                    {prefs?.dashboard?.showContainerStats && container.state === 'running' && (
                      <span className="text-xs font-mono text-muted-foreground flex-shrink-0 whitespace-nowrap">
                        {container.cpu_percent !== null ? `${container.cpu_percent.toFixed(1)}%` : '—'}
                        {' / '}
                        {container.memory_percent !== null ? `${container.memory_percent.toFixed(0)}MB` : '—'}
                      </span>
                    )}

                    {/* Container Kebab Menu */}
                    <div onClick={(e) => e.stopPropagation()}>
                      <DropdownMenu
                        trigger={
                          <button
                            className="text-muted-foreground hover:text-foreground p-1 flex-shrink-0"
                            aria-label="Container actions"
                          >
                            <MoreVertical className="w-3 h-3" />
                          </button>
                        }
                      >
                        {/* Start/Stop - conditional based on container state */}
                        {container.state === 'running' ? (
                          <>
                            <DropdownMenuItem
                              onClick={() => handleContainerAction(container.id, 'stop')}
                              icon={<Square />}
                            >
                              Stop
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={() => handleContainerAction(container.id, 'restart')}
                              icon={<RotateCcw />}
                            >
                              Restart
                            </DropdownMenuItem>
                          </>
                        ) : (
                          <DropdownMenuItem
                            onClick={() => handleContainerAction(container.id, 'start')}
                            icon={<Play />}
                          >
                            Start
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                          onClick={() => handleContainerAction(container.id, 'logs')}
                          icon={<ScrollText />}
                        >
                          View Logs
                        </DropdownMenuItem>
                        {/* WebUI - only show if configured */}
                        {container.web_ui_url && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onClick={() => window.open(container.web_ui_url!, '_blank', 'noopener,noreferrer')}
                              icon={<ExternalLink />}
                            >
                              Open WebUI
                            </DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenu>
                    </div>
                </div>
              ))}
            </div>
          </div>

        </div>
      )}

      {/* Footer - Container Count Badge */}
      <div className="flex items-center gap-4 text-xs border-t border-border pt-3 flex-shrink-0 mt-auto">
        {hasContainers && (
          <div className="flex items-center gap-1 text-muted-foreground">
            <Container className="w-3 h-3" />
            <span>
              {host.containers!.running} / {host.containers!.total}
            </span>
          </div>
        )}

        {/* Updates available */}
        {host.updates_available && host.updates_available > 0 && (
          <div className="flex items-center gap-1 text-info">
            <span>↑</span>
            <span>{host.updates_available}</span>
          </div>
        )}

        {/* Alerts */}
        {host.alerts && host.alerts.open > 0 && (
          <div className="flex items-center gap-1 text-destructive">
            <span>⚠</span>
            <span>{host.alerts.open}</span>
          </div>
        )}
      </div>
    </div>
  )
}
