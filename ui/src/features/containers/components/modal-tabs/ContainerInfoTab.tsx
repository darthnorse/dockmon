/**
 * ContainerInfoTab - Info content for Container Details Modal
 *
 * 2-column layout displaying:
 * LEFT COLUMN:
 * - Overview (Status with restart policy)
 * - WebUI URL
 * - Tags
 * - Image
 * - Ports
 * - Volumes
 *
 * RIGHT COLUMN:
 * - Auto-restart toggle
 * - Desired state selector
 * - Live Stats (CPU, Memory, Network with sparklines)
 * - Environment Variables (key: value pairs)
 */

import { useState, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/features/auth/AuthContext'
import { Cpu, MemoryStick, Network } from 'lucide-react'
import type { Container } from '../../types'
import { useContainerSparklines } from '@/lib/stats/StatsProvider'
import { ResponsiveMiniChart } from '@/lib/charts/ResponsiveMiniChart'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { TagInput } from '@/components/TagInput'
import { TagChip } from '@/components/TagChip'
import { Button } from '@/components/ui/button'
import { useContainerTagEditor } from '@/hooks/useContainerTagEditor'
import { makeCompositeKey } from '@/lib/utils/containerKeys'
import { formatBytes, formatNetworkRate } from '@/lib/utils/formatting'
import { sanitizeHref } from '@/lib/utils/urlSanitize'

const SYSTEM_ENV_VARS = ['PATH', 'HOME', 'HOSTNAME', 'TERM']

interface ContainerInfoTabProps {
  container: Container
}

export function ContainerInfoTab({ container }: ContainerInfoTabProps) {
  const { hasCapability } = useAuth()
  const canOperate = hasCapability('containers.operate')
  const canManageTags = hasCapability('tags.manage')
  const canViewEnv = hasCapability('containers.view_env')
  const containerShortId = container.id.slice(0, 12)

  const { data: inspectData, isError: inspectError } = useQuery({
    queryKey: ['container-inspect', container.host_id, containerShortId],
    queryFn: () => apiClient.get<Record<string, unknown>>(
      `/hosts/${container.host_id}/containers/${containerShortId}/inspect`
    ),
    enabled: canViewEnv,
    staleTime: 30_000,
    gcTime: 60_000,
    retry: 1,
  })

  const sparklines = useContainerSparklines(makeCompositeKey(container))
  const [autoRestart, setAutoRestart] = useState(false)
  const [desiredState, setDesiredState] = useState<'should_run' | 'on_demand' | 'unspecified'>('unspecified')
  const [webUiUrl, setWebUiUrl] = useState('')
  const [isEditingWebUi, setIsEditingWebUi] = useState(false)

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
    containerId: containerShortId,
    currentTags
  })

  const cpuData = sparklines?.cpu || []
  const memData = sparklines?.mem || []
  const netData = sparklines?.net || []

  useEffect(() => {
    setAutoRestart(container.auto_restart ?? false)

    const validStates: Array<'should_run' | 'on_demand' | 'unspecified'> = ['should_run', 'on_demand', 'unspecified']
    const containerState = container.desired_state as 'should_run' | 'on_demand' | 'unspecified' | undefined
    const newState = containerState && validStates.includes(containerState) ? containerState : 'unspecified'
    setDesiredState(newState)

    setWebUiUrl(container.web_ui_url || '')
  }, [container.auto_restart, container.desired_state, container.web_ui_url])

  const handleAutoRestartToggle = async (checked: boolean) => {
    setAutoRestart(checked)

    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${containerShortId}/auto-restart`, {
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
      await apiClient.post(`/hosts/${container.host_id}/containers/${containerShortId}/desired-state`, {
        desired_state: newState,
        container_name: container.name,
        web_ui_url: webUiUrl || null
      })
      toast.success(`Desired state set to "${newState}"`)
    } catch (error) {
      toast.error(`Failed to update desired state: ${error instanceof Error ? error.message : 'Unknown error'}`)
      setDesiredState(previousState)
    }
  }

  const handleSaveWebUiUrl = async () => {
    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${containerShortId}/desired-state`, {
        desired_state: desiredState,
        container_name: container.name,
        web_ui_url: webUiUrl || null
      })
      toast.success('WebUI URL saved')
      setIsEditingWebUi(false)
    } catch (error) {
      toast.error(`Failed to save WebUI URL: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  // Prefer inspect data (works for both agent and legacy hosts)
  // Fall back to container.env (populated for legacy hosts via HTTP)
  const filteredEnv = useMemo(() => {
    if (!canViewEnv) return []

    let envEntries: [string, string][] = []

    if (inspectData) {
      const config = inspectData.Config as Record<string, unknown> | undefined
      const envList = (config?.Env ?? []) as string[]
      envEntries = envList
        .filter((e): e is string => typeof e === 'string' && e.includes('='))
        .map((e) => {
          const idx = e.indexOf('=')
          return [e.slice(0, idx), e.slice(idx + 1)] as [string, string]
        })
    } else if (container.env) {
      envEntries = Object.entries(container.env)
    }

    return envEntries.filter(([key]) => !SYSTEM_ENV_VARS.includes(key))
  }, [canViewEnv, inspectData, container.env])

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
              <h4 className="text-lg font-medium text-foreground mb-3">Overview</h4>
              <div className="space-y-1.5">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">State</span>
                  {getStateColor()}
                </div>
                {container.restart_policy && (
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Docker Engine Restart Policy</span>
                    <span className="font-mono text-xs">{container.restart_policy}</span>
                  </div>
                )}
              </div>
            </div>

            {/* WebUI URL */}
            <fieldset disabled={!canOperate} className="disabled:opacity-60">
              <h4 className="text-lg font-medium text-foreground mb-3">WebUI</h4>
              {isEditingWebUi ? (
                <div className="space-y-2">
                  <input
                    type="url"
                    value={webUiUrl}
                    onChange={(e) => setWebUiUrl(e.target.value)}
                    placeholder="https://example.com:8080"
                    className="w-full px-3 py-2 text-sm bg-surface-1 border border-border rounded focus:outline-none focus:ring-2 focus:ring-primary"
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={handleSaveWebUiUrl}
                      className="flex-1"
                    >
                      Save
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setWebUiUrl(container.web_ui_url || '')
                        setIsEditingWebUi(false)
                      }}
                      className="flex-1"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div>
                  {webUiUrl ? (
                    <div className="flex items-center gap-2">
                      {sanitizeHref(webUiUrl) ? (
                        <a
                          href={sanitizeHref(webUiUrl)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm text-primary hover:underline truncate flex-1"
                        >
                          {webUiUrl}
                        </a>
                      ) : (
                        <span className="text-sm text-muted-foreground truncate flex-1">
                          {webUiUrl}
                        </span>
                      )}
                      <button
                        onClick={() => setIsEditingWebUi(true)}
                        className="text-xs text-primary hover:text-primary/80"
                      >
                        Edit
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setIsEditingWebUi(true)}
                      className="text-sm text-muted-foreground hover:text-foreground"
                    >
                      + Add URL
                    </button>
                  )}
                </div>
              )}
            </fieldset>

            {/* Tags */}
            <div>
              {isEditingTags ? (
                <fieldset disabled={!canManageTags} className="space-y-2 disabled:opacity-60">
                  <div className="flex items-center justify-between">
                    <h4 className="text-lg font-medium text-foreground">Tags</h4>
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
                </fieldset>
              ) : (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-lg font-medium text-foreground">Tags</h4>
                    <button
                      onClick={handleStartEdit}
                      disabled={!canManageTags}
                      className="text-xs text-primary hover:text-primary/80 disabled:opacity-60 disabled:cursor-not-allowed"
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
              <h4 className="text-lg font-medium text-foreground mb-3">Image</h4>
              <div className="text-sm font-mono bg-surface-1 px-3 py-2 rounded" data-testid="container-image">
                {container.image}
              </div>
            </div>

            {/* Ports */}
            {container.ports && container.ports.length > 0 && (
              <div>
                <h4 className="text-lg font-medium text-foreground mb-3">Ports</h4>
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
                <h4 className="text-lg font-medium text-foreground mb-3">Volumes</h4>
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
            {canViewEnv && (filteredEnv.length > 0 || inspectError) && (
              <div>
                <h4 className="text-lg font-medium text-foreground mb-3">Environment Variables</h4>
                {inspectError && filteredEnv.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Failed to load environment variables</p>
                ) : filteredEnv.length > 0 ? (
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
                ) : (
                  <p className="text-sm text-muted-foreground">No application environment variables</p>
                )}
              </div>
            )}
          </div>

          {/* RIGHT COLUMN */}
          <div className="space-y-6">
            <fieldset disabled={!canOperate} className="space-y-6 disabled:opacity-60">
              {/* Auto-restart Toggle */}
              <div>
                <h4 className="text-lg font-medium text-foreground mb-3">Auto-restart</h4>
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
                <h4 className="text-lg font-medium text-foreground mb-3">Desired State</h4>
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
            </fieldset>

            {/* Live Stats Header */}
            <div className="-mb-3">
              <h4 className="text-lg font-medium text-foreground">Live Stats</h4>
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
                    : '-'}
                </span>
              </div>
              {cpuData.length > 0 ? (
                <div className="h-[120px] w-full">
                  <ResponsiveMiniChart data={cpuData} color="cpu" height={120} showAxes={true} />
                </div>
              ) : (
                <div className="h-[120px] flex items-center justify-center text-muted-foreground text-xs">
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
                  {container.memory_usage ? formatBytes(container.memory_usage) : '-'}
                  {container.memory_limit && ` / ${formatBytes(container.memory_limit)}`}
                </span>
              </div>
              {memData.length > 0 ? (
                <div className="h-[120px] w-full">
                  <ResponsiveMiniChart data={memData} color="memory" height={120} showAxes={true} />
                </div>
              ) : (
                <div className="h-[120px] flex items-center justify-center text-muted-foreground text-xs">
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
                <div className="h-[120px] w-full">
                  <ResponsiveMiniChart data={netData} color="network" height={120} showAxes={true} />
                </div>
              ) : (
                <div className="h-[120px] flex items-center justify-center text-muted-foreground text-xs">
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
