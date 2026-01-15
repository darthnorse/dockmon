/**
 * Migration Choice Modal - Cloned VM Migration Selection
 *
 * When multiple remote/mTLS hosts share the same Docker engine_id (cloned VMs),
 * the user must choose which host to migrate settings from.
 *
 * This modal is NON-DISMISSABLE - user must make a choice.
 */

import { useState, useEffect } from 'react'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import { apiClient } from '@/lib/api/client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Server, ArrowRight, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

interface MigrationCandidate {
  host_id: string
  host_name: string
}

interface MigrationChoiceData {
  agent_id: string
  host_id: string
  host_name: string
  candidates: MigrationCandidate[]
}

export function MigrationChoiceModal() {
  const [choiceData, setChoiceData] = useState<MigrationChoiceData | null>(null)
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null)
  const { addMessageHandler } = useWebSocketContext()
  const queryClient = useQueryClient()

  // Listen for migration choice events
  useEffect(() => {
    const cleanup = addMessageHandler((message) => {
      if (message.type === 'migration_choice_needed') {
        const data = message.data as MigrationChoiceData
        setChoiceData(data)
        setSelectedHostId(null)
      }
    })

    return cleanup
  }, [addMessageHandler])

  // Mutation to perform the migration
  const migrateMutation = useMutation({
    mutationFn: async ({ agentId, sourceHostId }: { agentId: string; sourceHostId: string }) => {
      const response = await apiClient.post<Record<string, unknown>>(`/agent/${agentId}/migrate-from/${sourceHostId}`)
      return response
    },
    onSuccess: (data: Record<string, unknown>) => {
      const migratedFrom = data.migrated_from as { host_name: string } | undefined
      toast.success('Migration completed', {
        description: `Settings transferred from ${migratedFrom?.host_name || 'previous host'}`,
      })
      // Invalidate queries to refresh data
      queryClient.invalidateQueries({ queryKey: ['hosts'] })
      queryClient.invalidateQueries({ queryKey: ['containers'] })
      // Close modal
      setChoiceData(null)
      setSelectedHostId(null)
    },
    onError: (error: Error) => {
      toast.error('Migration failed', {
        description: error.message || 'Failed to migrate settings',
      })
    },
  })

  const handleMigrate = () => {
    if (!choiceData || !selectedHostId) return
    migrateMutation.mutate({
      agentId: choiceData.agent_id,
      sourceHostId: selectedHostId,
    })
  }

  // Don't render if no choice needed
  if (!choiceData) {
    return null
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      {/* Backdrop - no onClick to prevent dismissal */}
      <div className="absolute inset-0 bg-black/60" />

      {/* Modal */}
      <div className="relative bg-surface-1 rounded-lg shadow-xl border border-border max-w-lg w-full mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center h-10 w-10 rounded-full bg-warning/10">
              <AlertTriangle className="h-6 w-6 text-warning" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">
                Migration Choice Required
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                Multiple hosts share the same Docker engine ID
              </p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-4 space-y-4">
          <div className="text-sm text-foreground">
            <p>
              The agent <span className="font-medium text-foreground">{choiceData.host_name}</span> connected
              but found multiple existing hosts with the same Docker engine ID.
            </p>
            <p className="mt-2 text-muted-foreground">
              This typically happens with cloned VMs or LXC containers. Select which host&apos;s
              settings (tags, auto-restart configs, etc.) should be migrated to the new agent.
            </p>
          </div>

          {/* Agent info */}
          <div className="flex items-center gap-3 p-3 rounded-lg bg-surface-2 border border-border">
            <Server className="h-5 w-5 text-primary flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-foreground truncate">
                {choiceData.host_name}
              </div>
              <div className="text-xs text-muted-foreground">
                New agent connection
              </div>
            </div>
          </div>

          {/* Candidates list */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">
              Migrate settings from:
            </label>
            <div className="space-y-2">
              {choiceData.candidates.map((candidate) => (
                <label
                  key={candidate.host_id}
                  className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                    selectedHostId === candidate.host_id
                      ? 'bg-primary/10 border-primary'
                      : 'bg-surface-2 border-border hover:border-muted-foreground'
                  }`}
                >
                  <input
                    type="radio"
                    name="migration-source"
                    value={candidate.host_id}
                    checked={selectedHostId === candidate.host_id}
                    onChange={() => setSelectedHostId(candidate.host_id)}
                    className="h-4 w-4 text-primary"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">
                      {candidate.host_name}
                    </div>
                    <div className="text-xs text-muted-foreground truncate">
                      {candidate.host_id}
                    </div>
                  </div>
                  {selectedHostId === candidate.host_id && (
                    <ArrowRight className="h-4 w-4 text-primary flex-shrink-0" />
                  )}
                </label>
              ))}
            </div>
          </div>

          {/* Info note */}
          <div className="text-xs text-muted-foreground bg-surface-2 rounded p-3 space-y-2">
            <p>
              <strong>Migration:</strong> The selected host will be marked as migrated and its settings
              (tags, auto-restart configs, desired states, etc.) will be transferred to the new agent.
              The old host will remain in the system for reference but will be inactive.
            </p>
            <p className="text-warning">
              <strong>Important:</strong> You can only migrate ONE host per duplicate engine ID.
              Other cloned hosts will fail to register as agents until you regenerate their Docker engine ID.
            </p>
            <p>
              To fix other cloned hosts: <code className="px-1 py-0.5 bg-surface-1 rounded text-foreground">rm /var/lib/docker/engine-id</code> (or <code className="px-1 py-0.5 bg-surface-1 rounded text-foreground">/etc/docker/key.json</code> on older systems) and restart Docker.{' '}
              <a
                href="https://github.com/darthnorse/dockmon/wiki/Cloned-VMs-and-Duplicate-Engine-IDs"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                Learn more
              </a>
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border flex items-center justify-end gap-2">
          <button
            onClick={handleMigrate}
            disabled={!selectedHostId || migrateMutation.isPending}
            className="px-4 py-2 text-sm font-medium rounded transition-colors bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {migrateMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Migrating...
              </>
            ) : (
              'Migrate Settings'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
