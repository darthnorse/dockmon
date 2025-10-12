/**
 * HostOverviewTab Component
 *
 * Overview tab for host modal
 * - Large performance charts (CPU, Memory, Network)
 * - Time range selector
 * - Right sidebar with Host Information and Events
 */

import { Cpu, MemoryStick, Network, Plus } from 'lucide-react'
import { useHostMetrics, useHostSparklines } from '@/lib/stats/StatsProvider'
import { MiniChart } from '@/lib/charts/MiniChart'
import { TagInput } from '@/components/TagInput'
import { TagChip } from '@/components/TagChip'
import { Button } from '@/components/ui/button'
import { useHostTagEditor } from '@/hooks/useHostTagEditor'
import type { Host } from '@/types/api'

interface HostOverviewTabProps {
  hostId: string
  host: Host
}

export function HostOverviewTab({ hostId, host }: HostOverviewTabProps) {
  const metrics = useHostMetrics(hostId)
  const sparklines = useHostSparklines(hostId)

  const currentTags = host.tags || []

  const {
    isEditing: isEditingTags,
    editedTags,
    tagSuggestions,
    isLoading: isLoadingTags,
    setEditedTags,
    handleStartEdit,
    handleCancelEdit,
    handleSaveTags,
  } = useHostTagEditor({ hostId, currentTags })

  // Format network rate (bytes/sec to KB/s or MB/s)
  const formatNetworkRate = (bytesPerSec: number | undefined): string => {
    if (!bytesPerSec) return '0 B/s'

    if (bytesPerSec < 1024) return `${bytesPerSec.toFixed(0)} B/s`
    if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`
    return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`
  }

  // Format bytes to human readable
  const formatBytes = (bytes: number | undefined): string => {
    if (!bytes) return '0 B'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let value = bytes
    let unitIndex = 0
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024
      unitIndex++
    }
    return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unitIndex]}`
  }

  // Mock events data (replace with real data)
  const mockEvents = [
    { time: '15:32', type: 'Container', action: 'failed to start', severity: 'error' },
    { time: '14:58', type: 'Warning', action: 'High memory', severity: 'warning' },
    { time: '14:17', type: 'Warning', action: 'High memory', severity: 'warning' },
  ]

  return (
    <div className="flex h-full">
      {/* Main Content */}
      <div className="flex-1 p-6 overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold">Overview</h2>
        </div>

        {/* Performance Charts Grid */}
        <div className="grid grid-cols-1 gap-6">
          {/* CPU Usage */}
          <div className="bg-surface-2 rounded-lg p-6 border border-border">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Cpu className="h-5 w-5 text-amber-500" />
                <span className="font-medium">CPU Usage</span>
              </div>
              <span className="text-sm text-muted-foreground">
                {metrics?.cpu_percent !== undefined
                  ? `${metrics.cpu_percent.toFixed(0)}%`
                  : '—'}
              </span>
            </div>
            {sparklines?.cpu && sparklines.cpu.length > 0 ? (
              <div className="h-[120px]">
                <MiniChart
                  data={sparklines.cpu}
                  color="cpu"
                  height={120}
                  width={800}
                />
              </div>
            ) : (
              <div className="h-[120px] flex items-center justify-center bg-muted rounded text-xs text-muted-foreground">
                No data available
              </div>
            )}
          </div>

          {/* Memory Usage */}
          <div className="bg-surface-2 rounded-lg p-6 border border-border">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <MemoryStick className="h-5 w-5 text-blue-500" />
                <span className="font-medium">Memory Usage</span>
              </div>
              <span className="text-sm text-muted-foreground">
                {metrics?.mem_bytes
                  ? `${formatBytes(metrics.mem_bytes)}`
                  : '—'}
              </span>
            </div>
            {sparklines?.mem && sparklines.mem.length > 0 ? (
              <div className="h-[120px]">
                <MiniChart
                  data={sparklines.mem}
                  color="memory"
                  height={120}
                  width={800}
                />
              </div>
            ) : (
              <div className="h-[120px] flex items-center justify-center bg-muted rounded text-xs text-muted-foreground">
                No data available
              </div>
            )}
          </div>

          {/* Network Traffic */}
          <div className="bg-surface-2 rounded-lg p-6 border border-border">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Network className="h-5 w-5 text-green-500" />
                <span className="font-medium">Network Traffic</span>
              </div>
              <span className="text-sm text-muted-foreground">
                {metrics?.net_bytes_per_sec !== undefined
                  ? formatNetworkRate(metrics.net_bytes_per_sec)
                  : '—'}
              </span>
            </div>
            {sparklines?.net && sparklines.net.length > 0 ? (
              <div className="h-[120px]">
                <MiniChart
                  data={sparklines.net}
                  color="network"
                  height={120}
                  width={800}
                />
              </div>
            ) : (
              <div className="h-[120px] flex items-center justify-center bg-muted rounded text-xs text-muted-foreground">
                No data available
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right Sidebar */}
      <div className="w-80 border-l border-border p-6 overflow-y-auto shrink-0">
        {/* Host Information */}
        <div className="mb-8">
          <h3 className="text-lg font-semibold mb-4">Host information</h3>
          <div className="space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Address</span>
              <span className="font-mono text-xs">{host.url || '—'}</span>
            </div>

            {/* Tags Row */}
            <div>
              {isEditingTags ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Tags</span>
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
                      Save
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleCancelEdit}
                      disabled={isLoadingTags}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start justify-between text-sm gap-2">
                  <span className="text-muted-foreground shrink-0">Tags</span>
                  <div className="flex flex-wrap gap-1.5 justify-end">
                    {currentTags.length === 0 ? (
                      <span className="text-xs text-muted-foreground">No tags</span>
                    ) : (
                      (currentTags as string[]).map((tag) => (
                        <TagChip key={tag} tag={tag} size="sm" />
                      ))
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleStartEdit}
                      className="h-5 px-1.5 text-xs -mr-1.5"
                    >
                      <Plus className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">OS</span>
              <span>{host.os_version || 'Unknown'}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Docker Version</span>
              <span>{host.docker_version || '—'}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">CPU</span>
              <span>{host.num_cpus || '—'}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Memory</span>
              <span>{host.total_memory ? formatBytes(host.total_memory) : '—'}</span>
            </div>
          </div>
        </div>

        {/* Events */}
        <div>
          <h3 className="text-lg font-semibold mb-4">Events</h3>
          <div className="space-y-3">
            {mockEvents.map((event, index) => (
              <div key={index} className="text-sm">
                <div className="flex items-start gap-2">
                  <span className="text-muted-foreground">{event.time}</span>
                  <span
                    className={`px-2 py-0.5 rounded text-xs ${
                      event.severity === 'error'
                        ? 'bg-red-500/20 text-red-500'
                        : 'bg-yellow-500/20 text-yellow-500'
                    }`}
                  >
                    {event.type}
                  </span>
                  <span className="text-muted-foreground">{event.action}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Alerts section */}
          <div className="mt-8 pt-8 border-t border-border">
            <h3 className="text-lg font-semibold mb-4">Alerts</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Action</span>
                <span className="text-muted-foreground">Alert</span>
              </div>
              {mockEvents.map((event, index) => (
                <div key={index} className="flex items-start gap-2 text-sm">
                  <span className="text-muted-foreground">{event.time}</span>
                  <span
                    className={`px-2 py-0.5 rounded text-xs ${
                      event.severity === 'error'
                        ? 'bg-red-500/20 text-red-500'
                        : 'bg-yellow-500/20 text-yellow-500'
                    }`}
                  >
                    {event.severity === 'error' ? 'Error' : 'Warning'}
                  </span>
                  <span className="text-muted-foreground flex-1">{event.action}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
