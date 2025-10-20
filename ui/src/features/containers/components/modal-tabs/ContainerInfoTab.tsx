/**
 * ContainerInfoTab - Info content for Container Details Modal
 *
 * 2-column layout displaying:
 * LEFT COLUMN:
 * - Status (with restart policy)
 * - Image
 * - Labels (key: value pairs)
 * - Ports
 * - Volumes
 *
 * RIGHT COLUMN:
 * - CPU usage with sparkline
 * - Memory usage with sparkline
 * - Network I/O with sparkline
 * - Environment Variables (key: value pairs)
 * - Auto-restart toggle
 * - Desired state selector
 */

import { useState, useEffect, useMemo } from 'react'
import { Cpu, MemoryStick, Network } from 'lucide-react'
import type { Container } from '../../types'
import { useContainerSparklines } from '@/lib/stats/StatsProvider'
import { MiniChart } from '@/lib/charts/MiniChart'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { TagInput } from '@/components/TagInput'
import { TagChip } from '@/components/TagChip'
import { Button } from '@/components/ui/button'
import { useContainerTagEditor } from '@/hooks/useContainerTagEditor'
import { makeCompositeKey } from '@/lib/utils/containerKeys'

interface ContainerInfoTabProps {
  container: Container
}

export function ContainerInfoTab({ container }: ContainerInfoTabProps) {
  const sparklines = useContainerSparklines(makeCompositeKey(container))
  const [autoRestart, setAutoRestart] = useState(false)
  const [desiredState, setDesiredState] = useState<'should_run' | 'on_demand' | 'unspecified'>('unspecified')

  // Tag editor
  const currentTags = container.tags || []
  const {
    isEditing: isEditingTags,
    editedTags,
    tagSuggestions,
    isLoading: isLoadingTags,
    setEditedTags,
    handleStartEdit,
    handleCancelEdit,
    handleSaveTags,
  } = useContainerTagEditor({
    hostId: container.host_id || '',
    containerId: container.id,
    currentTags
  })

  // Memoize sparkline arrays - using length and checksum for efficient comparison
  const cpuData = useMemo(() => sparklines?.cpu || [], [sparklines?.cpu?.length, sparklines?.cpu?.join(',')])
  const memData = useMemo(() => sparklines?.mem || [], [sparklines?.mem?.length, sparklines?.mem?.join(',')])
  const netData = useMemo(() => sparklines?.net || [], [sparklines?.net?.length, sparklines?.net?.join(',')])

  // Initialize auto-restart and desired state
  useEffect(() => {
    setAutoRestart(container.auto_restart ?? false)

    const validStates: Array<'should_run' | 'on_demand' | 'unspecified'> = ['should_run', 'on_demand', 'unspecified']
    const containerState = container.desired_state as 'should_run' | 'on_demand' | 'unspecified' | undefined
    const newState = containerState && validStates.includes(containerState) ? containerState : 'unspecified'
    setDesiredState(newState)
  }, [container.auto_restart, container.desired_state])

  const handleAutoRestartToggle = async (checked: boolean) => {
    setAutoRestart(checked)

    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${container.id}/auto-restart`, {
        enabled: checked,
        container_name: container.name
      })
      toast.success(`Auto-restart ${checked ? 'enabled' : 'disabled'}`)
    } catch (error) {
      toast.error(`Failed to update auto-restart: ${error instanceof Error ? error.message : 'Unknown error'}`)
      setAutoRestart(!checked)
    }
  }

  const handleDesiredStateChange = async (newState: string) => {
    const previousState = desiredState
    setDesiredState(newState as typeof desiredState)

    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${container.id}/desired-state`, {
        desired_state: newState,
        container_name: container.name
      })
      toast.success(`Desired state set to "${newState}"`)
    } catch (error) {
      toast.error(`Failed to update desired state: ${error instanceof Error ? error.message : 'Unknown error'}`)
      setDesiredState(previousState)
    }
  }

  const formatBytes = (bytes: number | null | undefined): string => {
    if (!bytes) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
  }

  const formatNetworkRate = (bytesPerSec: number | null | undefined): string => {
    if (!bytesPerSec) return '0 B/s'
    const k = 1024
    if (bytesPerSec < k) return `${bytesPerSec.toFixed(0)} B/s`
    if (bytesPerSec < k * k) return `${(bytesPerSec / k).toFixed(2)} KB/s`
    return `${(bytesPerSec / (k * k)).toFixed(2)} MB/s`
  }

  // Filter out common system env vars for cleaner display
  const filteredEnv = container.env
    ? Object.entries(container.env).filter(([key]) => {
        // Show app-specific variables, hide common system paths
        return !['PATH', 'HOME', 'HOSTNAME', 'TERM'].includes(key)
      })
    : []

  // Get state color based on desired state and current state
  const getStateColor = () => {
    const state = container.state.toLowerCase()
    const desired = desiredState

    // If should_run but not running -> amber/yellow (warning)
    if (desired === 'should_run' && state !== 'running') {
      return <span className="text-warning">Stopped (Should Run)</span>
    }

    // Otherwise use standard colors
    switch (state) {
      case 'running':
        return <span className="text-success">Running</span>
      case 'paused':
        return <span className="text-warning">Paused</span>
      case 'restarting':
        return <span className="text-info">Restarting</span>
      case 'exited':
      case 'dead':
        return <span className="text-danger">Stopped</span>
      default:
        return <span className="text-muted-foreground capitalize">{state}</span>
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="p-6">
        <div className="grid grid-cols-2 gap-6">
          {/* LEFT COLUMN */}
          <div className="space-y-6">
            {/* Overview */}
            <div>
              <h4 className="text-base font-medium text-foreground mb-3">Overview</h4>
              <div className="space-y-1.5">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">State</span>
                  {getStateColor()}
                </div>
                {container.restart_policy && (
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Restart Policy</span>
                    <span className="font-mono text-xs">{container.restart_policy}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Tags */}
            <div>
              {isEditingTags ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-base font-medium text-foreground">Tags</h4>
                  </div>
                  <TagInput
                    value={editedTags}
                    onChange={setEditedTags}
                    suggestions={tagSuggestions}
                    placeholder="Add tags..."
                    maxTags={20}
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={handleSaveTags}
                      disabled={isLoadingTags}
                      className="flex-1"
                    >
                      {isLoadingTags ? 'Saving...' : 'Save'}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleCancelEdit}
                      disabled={isLoadingTags}
                      className="flex-1"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-base font-medium text-foreground">Tags</h4>
                    <button
                      onClick={handleStartEdit}
                      className="text-xs text-primary hover:text-primary/80"
                    >
                      + Edit
                    </button>
                  </div>
                  {currentTags.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {currentTags.map((tag) => (
                        <TagChip key={tag} tag={tag} />
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">No tags</p>
                  )}
                </div>
              )}
            </div>

            {/* Image */}
            <div>
              <h4 className="text-base font-medium text-foreground mb-3">Image</h4>
              <div className="text-sm font-mono bg-surface-1 px-3 py-2 rounded" data-testid="container-image">
                {container.image}
              </div>
            </div>

            {/* Ports */}
            {container.ports && container.ports.length > 0 && (
              <div>
                <h4 className="text-base font-medium text-foreground mb-3">Ports</h4>
                <div className="flex flex-wrap gap-2">
                  {container.ports.map((port) => (
                    <div key={port} className="text-sm font-mono bg-surface-1 px-3 py-1.5 rounded">
                      {port}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Volumes */}
            {container.volumes && container.volumes.length > 0 && (
              <div>
                <h4 className="text-base font-medium text-foreground mb-3">Volumes</h4>
                <div className="space-y-1">
                  {container.volumes.map((volume) => (
                    <div key={volume} className="text-xs font-mono bg-surface-1 px-3 py-1.5 rounded break-all">
                      {volume}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Environment Variables */}
            {filteredEnv.length > 0 && (
              <div>
                <h4 className="text-base font-medium text-foreground mb-3">Environment Variables</h4>
                <div className="space-y-1.5 max-h-64 overflow-y-auto">
                  {filteredEnv.map(([key, value]) => (
                    <div key={key} className="flex justify-between text-sm gap-4">
                      <span className="text-muted-foreground font-mono flex-shrink-0">
                        {key}
                      </span>
                      <span className="font-mono truncate text-right">{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* RIGHT COLUMN */}
          <div className="space-y-6">
            {/* Auto-restart Toggle */}
            <div>
              <h4 className="text-base font-medium text-foreground mb-3">Auto-restart</h4>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoRestart}
                  onChange={(e) => handleAutoRestartToggle(e.target.checked)}
                  className="w-4 h-4 rounded border-border bg-surface-1 checked:bg-primary"
                />
                <span className="text-sm">
                  Automatically restart container if it stops unexpectedly
                </span>
              </label>
            </div>

            {/* Desired State */}
            <div>
              <h4 className="text-base font-medium text-foreground mb-3">Desired State</h4>
              <div className="flex gap-2">
                <button
                  onClick={() => handleDesiredStateChange('should_run')}
                  className={`flex-1 px-3 py-2 text-sm rounded transition-colors ${
                    desiredState === 'should_run'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-surface-1 hover:bg-surface-2'
                  }`}
                >
                  Should Run
                </button>
                <button
                  onClick={() => handleDesiredStateChange('on_demand')}
                  className={`flex-1 px-3 py-2 text-sm rounded transition-colors ${
                    desiredState === 'on_demand'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-surface-1 hover:bg-surface-2'
                  }`}
                >
                  On Demand
                </button>
                <button
                  onClick={() => handleDesiredStateChange('unspecified')}
                  className={`flex-1 px-3 py-2 text-sm rounded transition-colors ${
                    desiredState === 'unspecified'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-surface-1 hover:bg-surface-2'
                  }`}
                >
                  Unspecified
                </button>
              </div>
            </div>

            {/* Live Stats Header */}
            <div className="-mb-3">
              <h4 className="text-base font-medium text-foreground">Live Stats</h4>
            </div>

            {/* CPU */}
            <div className="bg-surface-2 rounded-lg p-3 border border-border overflow-hidden" data-testid="cpu-usage">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-amber-500" />
                  <span className="font-medium text-sm">CPU Usage</span>
                </div>
                <span className="text-xs text-muted-foreground">
                  {container.cpu_percent !== null && container.cpu_percent !== undefined
                    ? `${container.cpu_percent.toFixed(0)}%`
                    : '—'}
                </span>
              </div>
              {cpuData.length > 0 ? (
                <div className="h-[100px] w-full overflow-hidden">
                  <MiniChart data={cpuData} color="cpu" height={100} width={780} />
                </div>
              ) : (
                <div className="h-[100px] flex items-center justify-center text-muted-foreground text-xs">
                  No data available
                </div>
              )}
            </div>

            {/* Memory */}
            <div className="bg-surface-2 rounded-lg p-3 border border-border overflow-hidden" data-testid="memory-usage">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <MemoryStick className="h-4 w-4 text-green-500" />
                  <span className="font-medium text-sm">Memory Usage</span>
                </div>
                <span className="text-xs text-muted-foreground">
                  {container.memory_usage ? formatBytes(container.memory_usage) : '—'}
                  {container.memory_limit && ` / ${formatBytes(container.memory_limit)}`}
                </span>
              </div>
              {memData.length > 0 ? (
                <div className="h-[100px] w-full overflow-hidden">
                  <MiniChart data={memData} color="memory" height={100} width={780} />
                </div>
              ) : (
                <div className="h-[100px] flex items-center justify-center text-muted-foreground text-xs">
                  No data available
                </div>
              )}
            </div>

            {/* Network */}
            <div className="bg-surface-2 rounded-lg p-3 border border-border overflow-hidden" data-testid="network-io">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Network className="h-4 w-4 text-orange-500" />
                  <span className="font-medium text-sm">Network I/O</span>
                </div>
                <span className="text-xs text-muted-foreground">
                  {formatNetworkRate(container.net_bytes_per_sec)}
                </span>
              </div>
              {netData.length > 0 ? (
                <div className="h-[100px] w-full overflow-hidden">
                  <MiniChart data={netData} color="network" height={100} width={780} />
                </div>
              ) : (
                <div className="h-[100px] flex items-center justify-center text-muted-foreground text-xs">
                  No data available
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
