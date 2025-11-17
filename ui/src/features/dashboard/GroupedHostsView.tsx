/**
 * Grouped Hosts View - Group by Tags
 *
 * FEATURES:
 * - Groups hosts by primary (first) tag
 * - Collapsible section headers for each tag group
 * - Drag-and-drop within groups (react-grid-layout)
 * - Supports Standard and Expanded modes
 * - Persistent collapsed state per group
 * - Special "Untagged" group for hosts without tags
 */

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import GridLayout, { WidthProvider, type Layout } from 'react-grid-layout'
import { ChevronDown, ChevronRight, GripVertical } from 'lucide-react'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ExpandedHostCardContainer } from './components/ExpandedHostCardContainer'
import { HostCardContainer } from './components/HostCardContainer'
import { useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'
import type { Host } from '@/types/api'
import 'react-grid-layout/css/styles.css'

const ResponsiveGridLayout = WidthProvider(GridLayout)

interface GroupedHostsViewProps {
  hosts: Host[]
  onHostClick?: (hostId: string) => void
  onViewDetails?: (hostId: string) => void
  onEditHost?: (hostId: string) => void
  mode?: 'standard' | 'expanded'
}

interface HostGroup {
  tag: string
  hosts: Host[]
}

// Generate default layout for hosts within a group
function generateGroupLayout(hosts: Host[], mode: 'standard' | 'expanded'): Layout[] {
  if (mode === 'standard') {
    // Standard mode: 4 columns (3 units each)
    return hosts.map((host, index) => ({
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
    // Expanded mode: 3 columns (4 units each)
    return hosts.map((host, index) => ({
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
}

export function GroupedHostsView({ hosts, onHostClick, onViewDetails, onEditHost, mode = 'expanded' }: GroupedHostsViewProps) {
  const { data: prefs, isLoading } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const hasLoadedPrefs = useRef(false)

  // Group hosts by primary (first) tag
  const baseGroups = useMemo<HostGroup[]>(() => {
    const groupMap = new Map<string, Host[]>()

    hosts.forEach((host) => {
      const primaryTag = host.tags?.[0] || 'Untagged'
      if (!groupMap.has(primaryTag)) {
        groupMap.set(primaryTag, [])
      }
      groupMap.get(primaryTag)!.push(host)
    })

    // Convert to array
    return Array.from(groupMap.entries()).map(([tag, hosts]) => ({
      tag,
      hosts,
    }))
  }, [hosts])

  // Apply user-defined tag order, or use default alphabetical sort
  const groups = useMemo<HostGroup[]>(() => {
    const tagGroupOrder = prefs?.dashboard?.tagGroupOrder || []

    if (tagGroupOrder.length === 0) {
      // Default sort: alphabetically, but "Untagged" always last
      return baseGroups.sort((a, b) => {
        if (a.tag === 'Untagged') return 1
        if (b.tag === 'Untagged') return -1
        return a.tag.localeCompare(b.tag)
      })
    }

    // Apply custom order
    const ordered: HostGroup[] = []
    const remaining = new Map(baseGroups.map(g => [g.tag, g]))

    // Add groups in user-defined order
    tagGroupOrder.forEach(tag => {
      if (remaining.has(tag)) {
        ordered.push(remaining.get(tag)!)
        remaining.delete(tag)
      }
    })

    // Add any new groups not in the saved order (alphabetically, Untagged last)
    const newGroups = Array.from(remaining.values()).sort((a, b) => {
      if (a.tag === 'Untagged') return 1
      if (b.tag === 'Untagged') return -1
      return a.tag.localeCompare(b.tag)
    })

    return [...ordered, ...newGroups]
  }, [baseGroups, prefs?.dashboard?.tagGroupOrder])

  // Get collapsed groups from user preferences
  const collapsedGroups = useMemo(() => {
    return new Set<string>(prefs?.collapsed_groups || [])
  }, [prefs?.collapsed_groups])

  // Toggle group collapse state
  const toggleGroup = useCallback(
    (tag: string) => {
      const newCollapsedGroups = new Set(collapsedGroups)
      if (newCollapsedGroups.has(tag)) {
        newCollapsedGroups.delete(tag)
      } else {
        newCollapsedGroups.add(tag)
      }

      // Save to user preferences
      updatePreferences.mutate({
        collapsed_groups: Array.from(newCollapsedGroups),
      })
    },
    [collapsedGroups, updatePreferences]
  )

  // Mark that preferences have loaded
  useEffect(() => {
    if (!isLoading && prefs) {
      hasLoadedPrefs.current = true
    }
  }, [isLoading, prefs])

  // Drag-and-drop sensors
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  // Handle drag end - reorder groups
  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event

      if (over && active.id !== over.id) {
        const oldIndex = groups.findIndex((g) => g.tag === active.id)
        const newIndex = groups.findIndex((g) => g.tag === over.id)

        if (oldIndex !== -1 && newIndex !== -1) {
          const newGroups = arrayMove(groups, oldIndex, newIndex)
          const newOrder = newGroups.map((g) => g.tag)

          // Save new order to preferences
          updatePreferences.mutate({
            dashboard: {
              ...prefs?.dashboard,
              tagGroupOrder: newOrder,
            }
          })
        }
      }
    },
    [groups, updatePreferences, prefs?.dashboard]
  )

  // Don't render until prefs have loaded
  if (isLoading) {
    return (
      <div className="mt-4">
        <h2 className="text-lg font-semibold mb-4">Hosts (Grouped by Tag)</h2>
        <div className="min-h-[400px]" />
      </div>
    )
  }

  return (
    <div className="mt-4">
      <h2 className="text-lg font-semibold mb-4">Hosts (Grouped by Tag)</h2>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={groups.map((g) => g.tag)} strategy={verticalListSortingStrategy}>
          <div className="flex flex-col gap-6">
            {groups.map((group) => (
              <SortableGroupSection
                key={group.tag}
                group={group}
                mode={mode}
                isCollapsed={collapsedGroups.has(group.tag)}
                onToggle={() => toggleGroup(group.tag)}
                {...(onHostClick && { onHostClick })}
                {...(onViewDetails && { onViewDetails })}
                {...(onEditHost && { onEditHost })}
                dashboardPrefs={prefs}
                updateDashboardPrefs={(updates) => updatePreferences.mutate({
                  dashboard: {
                    ...prefs?.dashboard,
                    ...updates
                  }
                })}
                hasLoadedPrefs={hasLoadedPrefs.current}
              />
            ))}

            {groups.length === 0 && (
              <div className="p-8 border border-dashed border-border rounded-lg text-center text-muted-foreground">
                No hosts configured. Add a host to get started.
              </div>
            )}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  )
}

interface GroupSectionProps {
  group: HostGroup
  mode: 'standard' | 'expanded'
  isCollapsed: boolean
  onToggle: () => void
  onHostClick?: (hostId: string) => void
  onViewDetails?: (hostId: string) => void
  onEditHost?: (hostId: string) => void
  dashboardPrefs: any
  updateDashboardPrefs: (updates: any) => void
  hasLoadedPrefs: boolean
  dragHandleProps?: {
    attributes: any
    listeners: any
  }
}

function GroupSection({
  group,
  mode,
  isCollapsed,
  onToggle,
  onHostClick,
  onViewDetails,
  onEditHost,
  dashboardPrefs,
  updateDashboardPrefs,
  hasLoadedPrefs,
  dragHandleProps,
}: GroupSectionProps) {
  const layoutKey = `groupLayout_${group.tag}_${mode}`

  // Get layout for this group from the groupLayouts nested object
  const layout = useMemo(() => {
    const groupLayouts = dashboardPrefs?.dashboard?.groupLayouts || {}
    const storedLayout = groupLayouts[layoutKey] as Layout[] | undefined

    if (storedLayout && storedLayout.length === group.hosts.length) {
      const hostIds = new Set(group.hosts.map((h) => h.id))
      const allIdsValid = storedLayout.every((item) => hostIds.has(item.i))

      if (allIdsValid) {
        return storedLayout
      }
    }

    return generateGroupLayout(group.hosts, mode)
  }, [group.hosts, dashboardPrefs?.dashboard?.groupLayouts, mode, layoutKey])

  const [currentLayout, setCurrentLayout] = useState<Layout[]>(layout)

  // Update currentLayout when layout memo changes
  useEffect(() => {
    setCurrentLayout(layout)
  }, [layout])

  // Handle layout change
  const handleLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      setCurrentLayout(newLayout)

      if (!hasLoadedPrefs) {
        return
      }

      // Update the groupLayouts nested object
      const currentGroupLayouts = dashboardPrefs?.dashboard?.groupLayouts || {}
      updateDashboardPrefs({
        groupLayouts: {
          ...currentGroupLayouts,
          [layoutKey]: newLayout,
        },
      })
    },
    [updateDashboardPrefs, layoutKey, hasLoadedPrefs, dashboardPrefs?.dashboard?.groupLayouts]
  )

  const hostCount = group.hosts.length
  const statusCounts = useMemo(() => {
    const counts = { online: 0, offline: 0, error: 0 }
    group.hosts.forEach((host) => {
      const status = host.status === 'degraded' ? 'error' : host.status
      if (status === 'online' || status === 'offline' || status === 'error') {
        counts[status]++
      }
    })
    return counts
  }, [group.hosts])

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      {/* Group Header */}
      <div className="w-full flex items-center bg-muted/50 hover:bg-muted transition-colors border-b border-border">
        {/* Drag handle */}
        {dragHandleProps && (
          <div
            {...dragHandleProps.attributes}
            {...dragHandleProps.listeners}
            className="flex items-center px-3 py-3 cursor-grab active:cursor-grabbing"
            title="Drag to reorder groups"
          >
            <GripVertical className="h-5 w-5 text-muted-foreground" />
          </div>
        )}

        {/* Collapse/Expand button */}
        <button
          onClick={onToggle}
          className="flex-1 flex items-center justify-between px-4 py-3"
        >
          <div className="flex items-center gap-3">
            {isCollapsed ? (
              <ChevronRight className="h-5 w-5 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-5 w-5 text-muted-foreground" />
            )}
            <span className="font-semibold text-lg">
              {group.tag === 'Untagged' ? (
                <span className="text-muted-foreground italic">{group.tag}</span>
              ) : (
                group.tag
              )}
            </span>
            <span className="text-sm text-muted-foreground">
              ({hostCount} {hostCount === 1 ? 'host' : 'hosts'})
            </span>
          </div>

          {/* Status counts */}
          <div className="flex items-center gap-4 text-sm">
            {statusCounts.online > 0 && (
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-green-500" />
                <span>{statusCounts.online}</span>
              </div>
            )}
            {statusCounts.offline > 0 && (
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-gray-400" />
                <span>{statusCounts.offline}</span>
              </div>
            )}
            {statusCounts.error > 0 && (
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-red-500" />
                <span>{statusCounts.error}</span>
              </div>
            )}
          </div>
        </button>
      </div>

      {/* Group Content */}
      {!isCollapsed && (
        <div className="p-4">
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
            {group.hosts.map((host) => (
              <div key={host.id} className="widget-container relative">
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

                {/* Drag handle */}
                <div
                  className="host-card-drag-handle absolute left-0 top-0 cursor-move pointer-events-auto"
                  style={{
                    width: 'calc(100% - 60px)',
                    height: '48px',
                    zIndex: 10,
                  }}
                  title="Drag to reorder"
                />
              </div>
            ))}
          </ResponsiveGridLayout>
        </div>
      )}
    </div>
  )
}

/**
 * SortableGroupSection - Wrapper that makes GroupSection draggable
 */
function SortableGroupSection(props: GroupSectionProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: props.group.tag,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div ref={setNodeRef} style={style}>
      <GroupSection {...props} dragHandleProps={{ attributes, listeners }} />
    </div>
  )
}
