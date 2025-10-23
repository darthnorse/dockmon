/**
 * DockMon Update Notification Banner
 *
 * Shows when a new DockMon version is available from GitHub.
 * Similar to Portainer's update notification.
 *
 * BEHAVIOR:
 * - Checks every 6 hours for new releases
 * - Shows banner when: latest > current AND user hasn't dismissed this version
 * - Dismissal is per-version (shows again for next release)
 * - Displays in sidebar, above user menu
 */

import { useState, useEffect } from 'react'
import { X, Info, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api/client'

interface DockMonUpdateBannerProps {
  isCollapsed: boolean
}

interface Settings {
  app_version: string
  latest_available_version: string | null
  last_dockmon_update_check_at: string | null
  dismissed_dockmon_update_version: string | null
  update_available: boolean
}

export function DockMonUpdateBanner({ isCollapsed }: DockMonUpdateBannerProps) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Fetch settings and user prefs on mount and poll every 30 seconds
  useEffect(() => {
    const fetchData = async () => {
      try {
        const data = await apiClient.get<Settings>('/settings')
        setSettings(data)
        setIsLoading(false)
      } catch (error) {
        console.error('Failed to fetch DockMon update settings:', error)
        setIsLoading(false)
      }
    }

    // Initial fetch
    fetchData()

    // Poll every 30 seconds (settings already polled by other components)
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  const handleDismiss = async () => {
    if (!settings?.latest_available_version) return

    try {
      await apiClient.post('/user/dismiss-dockmon-update', {
        version: settings.latest_available_version,
      })

      // Refetch settings to get updated dismissed version
      const data = await apiClient.get<Settings>('/settings')
      setSettings(data)
    } catch (error) {
      console.error('Failed to dismiss DockMon update:', error)
    }
  }

  const handleSeeWhatsNew = () => {
    if (!settings?.latest_available_version) return

    const version = settings.latest_available_version.replace(/^v/, '')
    const url = `https://github.com/darthnorse/dockmon/releases/tag/v${version}`
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  // Don't show if loading, no update available, or user dismissed this version
  if (
    isLoading ||
    !settings?.update_available ||
    settings?.dismissed_dockmon_update_version === settings?.latest_available_version
  ) {
    return null
  }

  // Collapsed view (just icon with tooltip)
  if (isCollapsed) {
    return (
      <div
        className="mb-2 flex items-center justify-center rounded-lg bg-gradient-to-r from-blue-500/20 to-cyan-500/20 p-2 cursor-pointer hover:from-blue-500/30 hover:to-cyan-500/30 transition-all duration-200"
        title={`Update available: ${settings?.latest_available_version}`}
        onClick={handleSeeWhatsNew}
      >
        <Info className="h-4 w-4 text-blue-400" />
      </div>
    )
  }

  // Expanded view (full banner)
  return (
    <div className="mb-2 rounded-lg bg-gradient-to-r from-blue-500/20 to-cyan-500/20 border border-blue-400/30 p-3 shadow-sm">
      <div className="flex items-start gap-2">
        <Info className="h-4 w-4 text-blue-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-foreground mb-1">
            Update available
          </div>
          <div className="text-xs text-muted-foreground mb-2">
            Version {settings?.latest_available_version}
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
