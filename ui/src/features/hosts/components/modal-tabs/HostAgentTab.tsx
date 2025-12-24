/**
 * Host Agent Tab
 *
 * Shows agent information and update controls for agent-based hosts.
 * Only shown for hosts with connection_type === 'agent'.
 *
 * FEATURES:
 * - Agent version, status, OS/arch info
 * - Update available badge
 * - Trigger update button (for systemd agents only)
 * - Deployment mode indicator (container vs systemd)
 */

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpCircle,
  CheckCircle,
  AlertCircle,
  RefreshCw,
  ExternalLink,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api/client'
import { cn } from '@/lib/utils'

interface HostAgentTabProps {
  hostId: string
}

interface AgentInfo {
  id: string
  version: string
  arch: string | null
  os: string | null
  status: string
  capabilities: Record<string, boolean>
  update_available: boolean
  latest_version: string | null
  is_container_mode: boolean
  last_seen_at: string | null
}

export function HostAgentTab({ hostId }: HostAgentTabProps) {
  const queryClient = useQueryClient()
  const [updateTriggered, setUpdateTriggered] = useState(false)

  // Fetch agent info
  const {
    data: agent,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['host-agent', hostId],
    queryFn: () => apiClient.get<AgentInfo>(`/hosts/${hostId}/agent`),
    refetchInterval: 10000, // Poll every 10s
  })

  // Reset updateTriggered when agent reconnects with new version (update_available becomes false)
  useEffect(() => {
    if (updateTriggered && agent && !agent.update_available) {
      setUpdateTriggered(false)
    }
  }, [agent?.update_available, updateTriggered])

  // Trigger agent update
  const triggerUpdate = useMutation({
    mutationFn: async () => {
      // Trigger self-update via agent WebSocket command
      await apiClient.post(`/hosts/${hostId}/agent/update`)
    },
    onSuccess: () => {
      setUpdateTriggered(true)
      queryClient.invalidateQueries({ queryKey: ['host-agent', hostId] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48 text-muted-foreground">
        <RefreshCw className="h-5 w-5 animate-spin mr-2" />
        Loading agent information...
      </div>
    )
  }

  if (error || !agent) {
    return (
      <div className="flex items-center justify-center h-48 text-muted-foreground">
        <AlertCircle className="h-5 w-5 mr-2" />
        Failed to load agent information
      </div>
    )
  }

  const lastSeenDate = agent.last_seen_at
    ? new Date(agent.last_seen_at).toLocaleString()
    : 'Never'

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="p-6">
        <div className="grid grid-cols-2 gap-6">
          {/* LEFT COLUMN */}
          <div className="space-y-6">
            {/* Agent Information */}
            <div>
              <h4 className="text-lg font-medium text-foreground mb-3">Agent Information</h4>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Status</span>
                  <span className={agent.status === 'online' ? 'text-green-500' : 'text-red-500'}>
                    {agent.status === 'online' ? 'Online' : 'Offline'}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Version</span>
                  <span>v{agent.version}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Platform</span>
                  <span>{agent.os || 'linux'}/{agent.arch || 'amd64'}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Deployment</span>
                  <span>{agent.is_container_mode ? 'Container' : 'Systemd'}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Last Seen</span>
                  <span>{lastSeenDate}</span>
                </div>
              </div>
            </div>

            {/* Links */}
            <div>
              <h4 className="text-lg font-medium text-foreground mb-3">Resources</h4>
              <Button
                variant="outline"
                size="sm"
                onClick={() => window.open(
                  `https://github.com/darthnorse/dockmon/releases/tag/agent-v${agent.version}`,
                  '_blank'
                )}
              >
                <ExternalLink className="h-4 w-4 mr-2" />
                Release Notes
              </Button>
            </div>
          </div>

          {/* RIGHT COLUMN */}
          <div className="space-y-6">
            {/* Status Banner */}
            <div
              className={cn(
                'rounded-lg border p-3',
                agent.status === 'online'
                  ? 'bg-green-500/10 border-green-500/30'
                  : 'bg-red-500/10 border-red-500/30'
              )}
            >
              <div className="flex items-center gap-2">
                {agent.status === 'online' ? (
                  <CheckCircle className="h-4 w-4 text-green-500" />
                ) : (
                  <AlertCircle className="h-4 w-4 text-red-500" />
                )}
                <span className="text-sm font-medium">
                  Agent is {agent.status}
                </span>
              </div>
            </div>

            {/* Update Available Banner */}
            {agent.update_available && !updateTriggered && (
              <div className="rounded-lg border bg-amber-500/10 border-amber-500/30 p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ArrowUpCircle className="h-4 w-4 text-amber-500" />
                    <div>
                      <div className="text-sm font-medium">Update available</div>
                      <div className="text-xs text-muted-foreground">
                        v{agent.latest_version} (current: v{agent.version})
                      </div>
                    </div>
                  </div>
                  {!agent.is_container_mode && (
                    <Button
                      onClick={() => triggerUpdate.mutate()}
                      disabled={triggerUpdate.isPending}
                      size="sm"
                    >
                      {triggerUpdate.isPending ? (
                        <>
                          <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                          Updating...
                        </>
                      ) : (
                        'Update'
                      )}
                    </Button>
                  )}
                </div>
                {agent.is_container_mode && (
                  <div className="mt-2 text-xs text-muted-foreground">
                    This agent runs in a container. Update DockMon to update the agent.
                  </div>
                )}
              </div>
            )}

            {/* Update In Progress */}
            {updateTriggered && (
              <div className="rounded-lg border bg-blue-500/10 border-blue-500/30 p-3">
                <div className="flex items-center gap-2">
                  <RefreshCw className="h-4 w-4 text-blue-500 animate-spin" />
                  <div>
                    <div className="text-sm font-medium">Update in progress</div>
                    <div className="text-xs text-muted-foreground">
                      Agent will reconnect shortly...
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
