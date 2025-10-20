/**
 * Compact Grouped Hosts View - Group by Tags (Compact Mode)
 *
 * FEATURES:
 * - Groups hosts by primary (first) tag
 * - Collapsible section headers for each tag group
 * - Simple vertical list (no grid layout)
 * - Draggable group headers for reordering
 * - Persistent collapsed state per group
 * - Persistent group order
 * - Special "Untagged" group for hosts without tags
 */

import { useMemo, useCallback, useEffect, useRef } from 'react'
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
import { CompactHostCard } from './components/CompactHostCard'
import { useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'

interface Host {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'error'
  tags?: string[]
}

interface CompactGroupedHostsViewProps {
  hosts: Host[]
  onHostClick?: (hostId: string) => void
}

interface HostGroup {
  tag: string
  hosts: Host[]
}

export function CompactGroupedHostsView({ hosts, onHostClick }: CompactGroupedHostsViewProps) {
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
    [collapsedGroups, updatePreferences.mutate]
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
          <div className="flex flex-col gap-4">
            {groups.map((group) => (
              <SortableCompactGroupSection
                key={group.tag}
                group={group}
                isCollapsed={collapsedGroups.has(group.tag)}
                onToggle={() => toggleGroup(group.tag)}
                onHostClick={onHostClick}
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

interface CompactGroupSectionProps {
  group: HostGroup
  isCollapsed: boolean
  onToggle: () => void
  onHostClick: ((hostId: string) => void) | undefined
  dragHandleProps?: {
    attributes: any
    listeners: any
  }
}

function CompactGroupSection({
  group,
  isCollapsed,
  onToggle,
  onHostClick,
  dragHandleProps,
}: CompactGroupSectionProps) {
  const hostCount = group.hosts.length
  const statusCounts = useMemo(() => {
    const counts = { online: 0, offline: 0, error: 0 }
    group.hosts.forEach((host) => {
      counts[host.status]++
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
            className="flex items-center px-3 py-2.5 cursor-grab active:cursor-grabbing"
            title="Drag to reorder groups"
          >
            <GripVertical className="h-4 w-4 text-muted-foreground" />
          </div>
        )}

        {/* Collapse/Expand button */}
        <button
          onClick={onToggle}
          className="flex-1 flex items-center justify-between px-4 py-2.5"
        >
          <div className="flex items-center gap-3">
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
            <span className="font-semibold text-base">
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
          <div className="flex items-center gap-3 text-sm">
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

      {/* Group Content - Sortable vertical list */}
      {!isCollapsed && (
        <div className="p-3">
          <SortableHostList group={group} onHostClick={onHostClick} />
        </div>
      )}
    </div>
  )
}

/**
 * SortableCompactGroupSection - Wrapper that makes CompactGroupSection draggable
 */
function SortableCompactGroupSection(props: Omit<CompactGroupSectionProps, 'dragHandleProps'>) {
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
      <CompactGroupSection {...props} dragHandleProps={{ attributes, listeners }} />
    </div>
  )
}

/**
 * SortableHostList - Sortable list of hosts within a group
 */
interface SortableHostListProps {
  group: HostGroup
  onHostClick: ((hostId: string) => void) | undefined
}

function SortableHostList({ group, onHostClick }: SortableHostListProps) {
  const { data: prefs } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const hasLoadedPrefs = useRef(false)

  // Key for storing this group's host order
  const orderKey = `compactGroupHostOrder_${group.tag}`

  // Apply saved order or use default
  const orderedHosts = useMemo(() => {
    const groupLayouts = prefs?.dashboard?.groupLayouts || {}
    const savedOrder = groupLayouts[orderKey] as string[] | undefined

    if (!savedOrder || savedOrder.length !== group.hosts.length) {
      return group.hosts
    }

    // Validate all IDs exist
    const hostMap = new Map(group.hosts.map((h) => [h.id, h]))
    const allIdsValid = savedOrder.every((id) => hostMap.has(id))

    if (!allIdsValid) {
      return group.hosts
    }

    // Apply saved order
    return savedOrder.map((id) => hostMap.get(id)!)
  }, [group.hosts, prefs?.dashboard?.groupLayouts, orderKey])

  // Mark that preferences have loaded
  useEffect(() => {
    if (prefs) {
      hasLoadedPrefs.current = true
    }
  }, [prefs])

  // Drag-and-drop sensors
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  // Handle drag end - reorder hosts
  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event

      if (over && active.id !== over.id) {
        const oldIndex = orderedHosts.findIndex((h) => h.id === active.id)
        const newIndex = orderedHosts.findIndex((h) => h.id === over.id)

        if (oldIndex !== -1 && newIndex !== -1) {
          const newHosts = arrayMove(orderedHosts, oldIndex, newIndex)
          const newOrder = newHosts.map((h) => h.id)

          // Save to groupLayouts (cast to any to allow string[] for host order keys)
          if (hasLoadedPrefs.current) {
            const currentGroupLayouts = prefs?.dashboard?.groupLayouts || {}
            updatePreferences.mutate({
              dashboard: {
                ...prefs?.dashboard,
                groupLayouts: {
                  ...currentGroupLayouts,
                  [orderKey]: newOrder as any,
                },
              }
            })
          }
        }
      }
    },
    [orderedHosts, updatePreferences.mutate, orderKey, prefs?.dashboard?.groupLayouts, prefs?.dashboard]
  )

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={orderedHosts.map((h) => h.id)} strategy={verticalListSortingStrategy}>
        <div className="flex flex-col gap-2">
          {orderedHosts.map((host) => (
            <SortableHostCard key={host.id} host={host} onHostClick={onHostClick} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  )
}

/**
 * SortableHostCard - Individual draggable host card
 * Left side (hostname) is clickable, right side is draggable area
 */
interface SortableHostCardProps {
  host: Host
  onHostClick: ((hostId: string) => void) | undefined
}

function SortableHostCard({ host, onHostClick }: SortableHostCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: host.id,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div ref={setNodeRef} style={style} className="relative">
      {/* Drag handle overlay - covers right side only */}
      <div
        {...attributes}
        {...listeners}
        className="absolute right-0 top-0 h-full cursor-grab active:cursor-grabbing"
        style={{ width: 'calc(100% - 200px)', zIndex: 10 }}
        title="Drag to reorder"
      />
      <CompactHostCard
        host={{
          id: host.id,
          name: host.name,
          url: host.url,
          status: host.status,
          ...(host.tags && { tags: host.tags }),
        }}
        {...(onHostClick && { onClick: () => onHostClick(host.id) })}
      />
    </div>
  )
}
