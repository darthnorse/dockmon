/**
 * Host Cards Grid - Using react-grid-layout
 *
 * FEATURES:
 * - Drag-and-drop host card positioning
 * - Resizable cards (responsive container columns)
 * - Persistent layout per user
 * - Supports both Standard and Expanded modes
 * - Same UX as widget dashboard above
 */

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { Responsive as ResponsiveGridLayout, WidthProvider, type Layout, type Layouts } from 'react-grid-layout'
import { ExpandedHostCardContainer } from './components/ExpandedHostCardContainer'
import { HostCardContainer } from './components/HostCardContainer'
import { useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'
import type { Host } from '@/types/api'
import 'react-grid-layout/css/styles.css'

const ResponsiveGrid = WidthProvider(ResponsiveGridLayout)

interface HostCardsGridProps {
  hosts: Host[]
  onHostClick?: (hostId: string) => void
  onViewDetails?: (hostId: string) => void
  onEditHost?: (hostId: string) => void
  mode?: 'standard' | 'expanded'
}

// Default layouts for host cards with responsive breakpoints
// Using 36px row height to align with container row height
function generateDefaultLayouts(hosts: Host[], mode: 'standard' | 'expanded'): Layouts {
  const layouts: Layouts = {}

  if (mode === 'standard') {
    // Mobile (xs): 1 column (12 units wide)
    layouts.xs = hosts.map((host, index) => ({
      i: host.id,
      x: 0,
      y: index * 8,
      w: 12,
      h: 8,
      minW: 12,
      minH: 6,
      maxW: 12,
      maxH: 20,
    }))

    // Tablet (sm): 2 columns (6 units each)
    layouts.sm = hosts.map((host, index) => ({
      i: host.id,
      x: (index % 2) * 6,
      y: Math.floor(index / 2) * 8,
      w: 6,
      h: 8,
      minW: 6,
      minH: 6,
      maxW: 12,
      maxH: 20,
    }))

    // Desktop (md): 3 columns (4 units each)
    layouts.md = hosts.map((host, index) => ({
      i: host.id,
      x: (index % 3) * 4,
      y: Math.floor(index / 3) * 8,
      w: 4,
      h: 8,
      minW: 3,
      minH: 6,
      maxW: 12,
      maxH: 20,
    }))

    // Large desktop (lg): 4 columns (3 units each)
    layouts.lg = hosts.map((host, index) => ({
      i: host.id,
      x: (index % 4) * 3,
      y: Math.floor(index / 4) * 8,
      w: 3,
      h: 8,
      minW: 3,
      minH: 6,
      maxW: 12,
      maxH: 20,
    }))
  } else {
    // Expanded mode
    // Mobile (xs): 1 column (12 units wide)
    layouts.xs = hosts.map((host, index) => ({
      i: host.id,
      x: 0,
      y: index * 10,
      w: 12,
      h: 10,
      minW: 12,
      minH: 6,
      maxW: 12,
      maxH: 30,
    }))

    // Tablet (sm): 2 columns (6 units each)
    layouts.sm = hosts.map((host, index) => ({
      i: host.id,
      x: (index % 2) * 6,
      y: Math.floor(index / 2) * 10,
      w: 6,
      h: 10,
      minW: 6,
      minH: 6,
      maxW: 12,
      maxH: 30,
    }))

    // Desktop (md+): 3 columns (4 units each)
    layouts.md = hosts.map((host, index) => ({
      i: host.id,
      x: (index % 3) * 4,
      y: Math.floor(index / 3) * 10,
      w: 4,
      h: 10,
      minW: 3,
      minH: 6,
      maxW: 12,
      maxH: 30,
    }))

    // Large desktop (lg): 3 columns (4 units each) - same as md for expanded
    layouts.lg = hosts.map((host, index) => ({
      i: host.id,
      x: (index % 3) * 4,
      y: Math.floor(index / 3) * 10,
      w: 4,
      h: 10,
      minW: 3,
      minH: 6,
      maxW: 12,
      maxH: 30,
    }))
  }

  return layouts
}

export function HostCardsGrid({ hosts, onHostClick, onViewDetails, onEditHost, mode = 'expanded' }: HostCardsGridProps) {
  const { data: prefs, isLoading } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const hasLoadedPrefs = useRef(false)

  // Use different layout keys for Standard vs Expanded modes
  const layoutKey = mode === 'standard' ? 'hostCardLayoutStandard' : 'hostCardLayout'

  // Get layouts from user prefs or generate default
  const layouts = useMemo(() => {
    const storedLayouts = prefs?.dashboard?.[layoutKey] as Layouts | undefined

    if (storedLayouts) {
      // Validate that stored layouts have all current host IDs
      const hostIds = new Set(hosts.map((h) => h.id))
      const hasValidLayouts = Object.values(storedLayouts).every(
        (layout) => layout && layout.length === hosts.length && layout.every((item) => hostIds.has(item.i))
      )

      if (hasValidLayouts) {
        // Use stored layouts - all host IDs match
        return storedLayouts
      }
    }

    // Generate default layouts
    return generateDefaultLayouts(hosts, mode)
  }, [hosts, prefs, mode, layoutKey])

  const [currentLayouts, setCurrentLayouts] = useState<Layouts>(layouts)

  // Update currentLayouts when layouts memo changes (e.g., when prefs load)
  useEffect(() => {
    setCurrentLayouts(layouts)
  }, [layouts])

  // Mark that preferences have loaded (so we can save changes)
  useEffect(() => {
    if (!isLoading && prefs) {
      hasLoadedPrefs.current = true
    }
  }, [isLoading, prefs])

  // Handle layout change (drag/resize)
  const handleLayoutChange = useCallback(
    (_currentLayout: Layout[], allLayouts: Layouts) => {
      setCurrentLayouts(allLayouts)

      // Don't save until preferences have loaded (react-grid-layout fires this on mount)
      if (!hasLoadedPrefs.current) {
        return
      }

      // Save to user prefs (debounced via React Query) using the correct layout key
      updatePreferences.mutate({
        dashboard: {
          ...prefs?.dashboard,
          [layoutKey]: allLayouts,
        }
      })
    },
    [updatePreferences, layoutKey, prefs?.dashboard]
  )

  // Don't render grid until prefs have loaded to prevent flash of default layout
  if (isLoading) {
    return (
      <div className="mt-4">
        <h2 className="text-lg font-semibold mb-4">Hosts</h2>
        <div className="min-h-[400px]" />
      </div>
    )
  }

  return (
    <div className="mt-4">
      <h2 className="text-lg font-semibold mb-4">Hosts</h2>

      <ResponsiveGrid
        className="layout"
        layouts={currentLayouts}
        onLayoutChange={handleLayoutChange}
        breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 0 }}
        cols={{ lg: 12, md: 12, sm: 12, xs: 12 }}
        rowHeight={36}
        draggableHandle=".host-card-drag-handle"
        compactType="vertical"
        preventCollision={false}
        isResizable={true}
        resizeHandles={['se', 'sw', 'ne', 'nw', 's', 'e', 'w']}
      >
        {hosts.map((host) => (
          <div key={host.id} className="widget-container relative">
            {/* Host card content - base layer */}
            <div className="h-full overflow-hidden">
              {mode === 'standard' ? (
                <HostCardContainer
                  host={host}
                  {...(onHostClick && { onHostClick })}
                  {...(onViewDetails && { onViewDetails })}
                  {...(onEditHost && { onEditHost })}
                />
              ) : (
                <ExpandedHostCardContainer
                  host={host}
                  {...(onHostClick && { onHostClick })}
                  {...(onViewDetails && { onViewDetails })}
                  {...(onEditHost && { onEditHost })}
                />
              )}
            </div>

            {/* Drag handle - covers header area only (like Standard mode) */}
            {/* Positioned above content but below resize handles */}
            {/* Left side of header is clickable via host-card-drag-handle-content class */}
            <div
              className="host-card-drag-handle absolute left-0 top-0 cursor-move pointer-events-auto"
              style={{
                width: 'calc(100% - 60px)',
                height: '64px',
                zIndex: 10
              }}
              title="Drag to reorder"
            />
          </div>
        ))}
      </ResponsiveGrid>

      {hosts.length === 0 && (
        <div className="p-8 border border-dashed border-border rounded-lg text-center text-muted-foreground">
          No hosts configured. Add a host to get started.
        </div>
      )}
    </div>
  )
}
