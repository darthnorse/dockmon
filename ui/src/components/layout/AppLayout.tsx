/**
 * App Layout - Main Application Shell
 *
 * ARCHITECTURE:
 * - Sidebar + Main content area
 * - Responsive padding based on sidebar state
 * - Handles sidebar collapsed state via database (syncs across devices)
 */

import { useState, useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { cn } from '@/lib/utils'
import { useSidebarCollapsed } from '@/lib/hooks/useUserPreferences'

export function AppLayout() {
  const { isCollapsed: dbCollapsed } = useSidebarCollapsed()

  // Track local sidebar state (updates faster than DB sync)
  const [isCollapsed, setIsCollapsed] = useState(dbCollapsed)

  // Sync local state with database state
  useEffect(() => {
    setIsCollapsed(dbCollapsed)
  }, [dbCollapsed])

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
    <div className="min-h-screen bg-background">
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
    </div>
  )
}
