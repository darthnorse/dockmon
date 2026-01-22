/**
 * Agent List Component for DockMon v2.2.0
 *
 * Displays all registered agents with their status and connection state
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Loader2, Server, CheckCircle2, XCircle, Clock } from 'lucide-react'
import { useAgents } from '../hooks/useAgents'
import { useTimeFormat } from '@/lib/hooks/useUserPreferences'
import { formatDateTime } from '@/lib/utils/timeFormat'
import type { Agent } from '../types'

function AgentStatusBadge({ agent }: { agent: Agent }) {
  if (agent.connected) {
    return (
      <Badge variant="default" className="bg-green-500">
        <CheckCircle2 className="h-3 w-3 mr-1" />
        Connected
      </Badge>
    )
  }

  if (agent.status === 'online') {
    return (
      <Badge variant="secondary">
        <Clock className="h-3 w-3 mr-1" />
        Online
      </Badge>
    )
  }

  return (
    <Badge variant="destructive">
      <XCircle className="h-3 w-3 mr-1" />
      Offline
    </Badge>
  )
}

function AgentCard({ agent }: { agent: Agent }) {
  const { timeFormat } = useTimeFormat()
  const formatDate = (isoString: string | null) => {
    if (!isoString) return 'Never'
    return formatDateTime(isoString, timeFormat)
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Server className="h-5 w-5 text-muted-foreground" />
            <div>
              <CardTitle className="text-base">
                {agent.host_name || 'Unknown Host'}
              </CardTitle>
              <CardDescription className="text-xs">
                {agent.engine_id.substring(0, 12)}
              </CardDescription>
            </div>
          </div>
          <AgentStatusBadge agent={agent} />
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <dt className="text-muted-foreground">Version</dt>
            <dd className="font-mono">{agent.version}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Protocol</dt>
            <dd className="font-mono">{agent.proto_version}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Last Seen</dt>
            <dd className="text-xs">{formatDate(agent.last_seen_at)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Registered</dt>
            <dd className="text-xs">{formatDate(agent.registered_at)}</dd>
          </div>
        </dl>

        {Object.keys(agent.capabilities).length > 0 && (
          <div className="mt-3">
            <dt className="text-sm text-muted-foreground mb-1">Capabilities</dt>
            <div className="flex flex-wrap gap-1">
              {agent.capabilities.stats_collection && (
                <Badge variant="outline" className="text-xs">Stats</Badge>
              )}
              {agent.capabilities.container_updates && (
                <Badge variant="outline" className="text-xs">Updates</Badge>
              )}
              {agent.capabilities.self_update && (
                <Badge variant="outline" className="text-xs">Self-Update</Badge>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function AgentList() {
  const { data, isLoading, isError, error } = useAgents()

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Loading agents...</span>
        </CardContent>
      </Card>
    )
  }

  if (isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {error?.message || 'Failed to load agents'}
        </AlertDescription>
      </Alert>
    )
  }

  if (!data || data.agents.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No Agents Registered</CardTitle>
          <CardDescription>
            Get started by generating a registration token and installing an agent on a remote host.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">Registered Agents</h3>
          <p className="text-sm text-muted-foreground">
            {data.total} agent{data.total !== 1 ? 's' : ''} registered,{' '}
            {data.connected_count} connected
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {data.agents.map((agent) => (
          <AgentCard key={agent.agent_id} agent={agent} />
        ))}
      </div>
    </div>
  )
}
