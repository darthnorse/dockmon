/**
 * App Layout - Main Application Shell
 *
 * ARCHITECTURE:
 * - Sidebar + Main content area
 * - Responsive padding based on sidebar state
 * - Handles sidebar collapsed state via database (syncs across devices)
 * - Manages upgrade welcome notice for v1 → v2 migrations
 */

import { useState, useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { BlackoutBanner } from './BlackoutBanner'
import { MigrationBanner } from './MigrationBanner'
import { UpgradeWelcomeModal } from '@/components/UpgradeWelcomeModal'
import { AppVersionProvider } from '@/lib/contexts/AppVersionContext'
import { cn } from '@/lib/utils'
import { useSidebarCollapsed } from '@/lib/hooks/useUserPreferences'
import { apiClient } from '@/lib/api/client'

export function AppLayout() {
  const { isCollapsed: dbCollapsed } = useSidebarCollapsed()

  // Track local sidebar state (updates faster than DB sync)
  const [isCollapsed, setIsCollapsed] = useState(dbCollapsed)

  // Upgrade notice state
  const [showUpgradeNotice, setShowUpgradeNotice] = useState(false)
  const [appVersion, setAppVersion] = useState('2.0.0') // Fallback version

  // Sync local state with database state
  useEffect(() => {
    setIsCollapsed(dbCollapsed)
  }, [dbCollapsed])

  // Check for upgrade notice on app load
  useEffect(() => {
    const checkUpgradeNotice = async () => {
      try {
        const response = await apiClient.get<{
          show_notice: boolean;
          from_version: string | null;
          to_version: string | null;
          version: string;
        }>('/upgrade-notice')

        // Store version from database
        if (response.version) {
          setAppVersion(response.version)
        }

        if (response.show_notice) {
          setShowUpgradeNotice(true)
        }
      } catch (error) {
        console.error('Failed to check upgrade notice:', error)
      }
    }

    checkUpgradeNotice()
  }, [])

  // Listen for sidebar toggle events (for immediate UI updates)
  useEffect(() => {
    const handleSidebarToggle = () => {
      // Re-read the state from the hook (which updates optimistically)
      setIsCollapsed((prev) => !prev)
    }

    window.addEventListener('sidebar-toggle', handleSidebarToggle)

    return () => {
      window.removeEventListener('sidebar-toggle', handleSidebarToggle)
    }
  }, [])

  return (
    <AppVersionProvider version={appVersion}>
      <div className="min-h-screen bg-background">
        {/* Blackout window notification banner */}
        <BlackoutBanner />

        {/* Host migration notification banner */}
        <MigrationBanner />

        <Sidebar />

        {/* Main Content Area */}
        <main
          className={cn(
            'min-h-screen transition-all duration-300',
            isCollapsed ? 'pl-18' : 'pl-60'
          )}
        >
          <Outlet />
        </main>

        {/* Upgrade Welcome Modal (v1 → v2) */}
        <UpgradeWelcomeModal
          open={showUpgradeNotice}
          onClose={() => setShowUpgradeNotice(false)}
        />
      </div>
    </AppVersionProvider>
  )
}
