/**
 * Agent Update Notification Banner
 *
 * Shows when agents need updates (systemd deployments only).
 * Similar to DockMonUpdateBanner but for agent binaries.
 *
 * BEHAVIOR:
 * - Shows when: agents_needing_update > 0 AND user hasn't dismissed this version
 * - Only relevant for systemd/native agent deployments
 * - Container-based agents auto-update with DockMon
 * - Dismissal is per-version (shows again for next release)
 * - Displays in sidebar, above DockMon update banner
 */

import { useState, useEffect } from 'react'
import { X, ArrowUpCircle, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api/client'

interface AgentUpdateBannerProps {
  isCollapsed: boolean
}

interface Settings {
  latest_agent_version: string | null
  latest_agent_release_url: string | null
  dismissed_agent_update_version: string | null
  agents_needing_update: number
}

export function AgentUpdateBanner({ isCollapsed }: AgentUpdateBannerProps) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Fetch settings on mount and poll every 30 seconds
  useEffect(() => {
    const fetchData = async () => {
      try {
        const data = await apiClient.get<Settings>('/settings')
        setSettings(data)
        setIsLoading(false)
      } catch (error) {
        console.error('Failed to fetch agent update settings:', error)
        setIsLoading(false)
      }
    }

    // Initial fetch
    fetchData()

    // Poll every 30 seconds
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  const handleDismiss = async () => {
    if (!settings?.latest_agent_version) return

    try {
      await apiClient.post('/user/dismiss-agent-update', {
        version: settings.latest_agent_version,
      })

      // Refetch settings to get updated dismissed version
      const data = await apiClient.get<Settings>('/settings')
      setSettings(data)
    } catch (error) {
      console.error('Failed to dismiss agent update:', error)
    }
  }

  const handleSeeWhatsNew = () => {
    if (!settings?.latest_agent_release_url) return
    window.open(settings.latest_agent_release_url, '_blank', 'noopener,noreferrer')
  }

  // Don't show if loading, no agents need updates, or user dismissed this version
  if (
    isLoading ||
    !settings?.agents_needing_update ||
    settings.agents_needing_update === 0 ||
    settings?.dismissed_agent_update_version === settings?.latest_agent_version
  ) {
    return null
  }

  const agentCount = settings.agents_needing_update

  // Collapsed view (just icon with tooltip)
  if (isCollapsed) {
    return (
      <div
        className="mb-2 flex items-center justify-center rounded-lg bg-gradient-to-r from-amber-500/20 to-orange-500/20 p-2 cursor-pointer hover:from-amber-500/30 hover:to-orange-500/30 transition-all duration-200"
        title={`${agentCount} agent${agentCount > 1 ? 's' : ''} need${agentCount === 1 ? 's' : ''} update`}
        onClick={handleSeeWhatsNew}
      >
        <ArrowUpCircle className="h-4 w-4 text-amber-400" />
      </div>
    )
  }

  // Expanded view (full banner)
  return (
    <div className="mb-2 rounded-lg bg-gradient-to-r from-amber-500/20 to-orange-500/20 border border-amber-400/30 p-3 shadow-sm">
      <div className="flex items-start gap-2">
        <ArrowUpCircle className="h-4 w-4 text-amber-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-foreground mb-1">
            Agent update available
          </div>
          <div className="text-xs text-muted-foreground mb-2">
            {agentCount} agent{agentCount > 1 ? 's' : ''} can update to v{settings?.latest_agent_version}
          </div>
          <div className="flex flex-col gap-1.5">
            <Button
              variant="outline"
              size="sm"
              className="w-full h-7 text-xs justify-start"
              onClick={handleSeeWhatsNew}
            >
              <ExternalLink className="h-3 w-3 mr-1.5" />
              See what's new
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="w-full h-7 text-xs justify-start text-muted-foreground hover:text-foreground"
              onClick={handleDismiss}
            >
              <X className="h-3 w-3 mr-1.5" />
              Dismiss
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
