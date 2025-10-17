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
import GridLayout, { WidthProvider, type Layout } from 'react-grid-layout'
import { ExpandedHostCardContainer } from './components/ExpandedHostCardContainer'
import { HostCardContainer } from './components/HostCardContainer'
import { useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'
import 'react-grid-layout/css/styles.css'

const ResponsiveGridLayout = WidthProvider(GridLayout)

interface Host {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'error'
  tags?: string[]
}

interface HostCardsGridProps {
  hosts: Host[]
  onHostClick?: (hostId: string) => void
  onViewDetails?: (hostId: string) => void
  onEditHost?: (hostId: string) => void
  mode?: 'standard' | 'expanded'
}

// Default layout for host cards
// Using 36px row height to align with container row height
function generateDefaultLayout(hosts: Host[], mode: 'standard' | 'expanded'): Layout[] {
  if (mode === 'standard') {
    // Standard mode: 4 columns (3 units each), smaller cards
    return hosts.map((host, index) => ({
      i: host.id,
      x: (index % 4) * 3, // 4 columns: 0, 3, 6, 9
      y: Math.floor(index / 4) * 8, // Stack cards vertically
      w: 3, // Width: 3 units (12/4 = 4 columns)
      h: 8, // Height: 8 units (8 * 36px = 288px default)
      minW: 3, // Minimum 3 units wide (fits header + stats)
      minH: 6, // Minimum 6 units tall (fits header + footer)
      maxW: 12, // Maximum full width
      maxH: 20, // Maximum height (20 * 36px = 720px)
    }))
  } else {
    // Expanded mode: 3 columns (4 units each), larger cards
    return hosts.map((host, index) => ({
      i: host.id,
      x: (index % 3) * 4, // 3 columns: 0, 4, 8
      y: Math.floor(index / 3) * 10, // Stack cards vertically
      w: 4, // Width: 4 units (12/3 = 3 columns)
      h: 10, // Height: 10 units (10 * 36px = 360px default)
      minW: 3, // Minimum 3 units wide
      minH: 6, // Minimum 6 units tall
      maxW: 12, // Maximum full width
      maxH: 30, // Maximum height (30 * 36px = 1080px for large container lists)
    }))
  }
}

export function HostCardsGrid({ hosts, onHostClick, onViewDetails, onEditHost, mode = 'expanded' }: HostCardsGridProps) {
  const { data: prefs, isLoading } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const hasLoadedPrefs = useRef(false)

  // Use different layout keys for Standard vs Expanded modes
  const layoutKey = mode === 'standard' ? 'hostCardLayoutStandard' : 'hostCardLayout'

  // Get layout from user prefs or generate default
  const layout = useMemo(() => {
    const storedLayout = prefs?.dashboard?.[layoutKey] as Layout[] | undefined

    if (storedLayout && storedLayout.length === hosts.length) {
      // Validate that all IDs in stored layout exist in current hosts
      const hostIds = new Set(hosts.map((h) => h.id))
      const allIdsValid = storedLayout.every((item) => hostIds.has(item.i))

      if (allIdsValid) {
        // Use stored layout - all host IDs match
        return storedLayout
      }
    }

    // Generate default layout
    return generateDefaultLayout(hosts, mode)
  }, [hosts, prefs, mode, layoutKey])

  const [currentLayout, setCurrentLayout] = useState<Layout[]>(layout)

  // Update currentLayout when layout memo changes (e.g., when prefs load)
  useEffect(() => {
    setCurrentLayout(layout)
  }, [layout])

  // Mark that preferences have loaded (so we can save changes)
  useEffect(() => {
    if (!isLoading && prefs) {
      hasLoadedPrefs.current = true
    }
  }, [isLoading, prefs])

  // Handle layout change (drag/resize)
  const handleLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      setCurrentLayout(newLayout)

      // Don't save until preferences have loaded (react-grid-layout fires this on mount)
      if (!hasLoadedPrefs.current) {
        return
      }

      // Save to user prefs (debounced via React Query) using the correct layout key
      updatePreferences.mutate({
        dashboard: {
          ...prefs?.dashboard,
          [layoutKey]: newLayout,
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

      <ResponsiveGridLayout
        className="layout"
        layout={currentLayout}
        onLayoutChange={handleLayoutChange}
        cols={12}
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
                  host={{
                    id: host.id,
                    name: host.name,
                    url: host.url,
                    status: host.status,
                    ...(host.tags && { tags: host.tags }),
                  }}
                  {...(onHostClick && { onHostClick })}
                  {...(onViewDetails && { onViewDetails })}
                  {...(onEditHost && { onEditHost })}
                />
              ) : (
                <ExpandedHostCardContainer
                  host={{
                    id: host.id,
                    name: host.name,
                    url: host.url,
                    status: host.status,
                    ...(host.tags && { tags: host.tags }),
                  }}
                  {...(onHostClick && { onHostClick })}
                  {...(onViewDetails && { onViewDetails })}
                  {...(onEditHost && { onEditHost })}
                />
              )}
            </div>

            {/* Drag handle - positioned above content but below resize handles */}
            {/* Excludes three-dots menu area and resize handle edges */}
            <div
              className="host-card-drag-handle absolute left-0 top-0 cursor-move pointer-events-auto"
              style={{
                width: 'calc(100% - 60px)',
                height: '48px',
                zIndex: 10
              }}
              title="Drag to reorder"
            />
          </div>
        ))}
      </ResponsiveGridLayout>

      {hosts.length === 0 && (
        <div className="p-8 border border-dashed border-border rounded-lg text-center text-muted-foreground">
          No hosts configured. Add a host to get started.
        </div>
      )}
    </div>
  )
}
