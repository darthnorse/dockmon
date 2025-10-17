/**
 * SortableCompactHostList - Drag-and-drop sortable compact host list
 *
 * FEATURES:
 * - Vertical drag-and-drop reordering
 * - Persistent host order
 * - Visual feedback during drag
 * - Uses @dnd-kit for smooth drag experience
 */

import { useMemo, useCallback, useEffect, useRef } from 'react'
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
import { CompactHostCard } from './CompactHostCard'
import { useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'

interface Host {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'error'
  tags?: string[]
}

interface SortableCompactHostListProps {
  hosts: Host[]
  onHostClick: (hostId: string) => void
}

export function SortableCompactHostList({ hosts, onHostClick }: SortableCompactHostListProps) {
  const { data: prefs, isLoading } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const hasLoadedPrefs = useRef(false)

  // Apply saved order or use default
  const orderedHosts = useMemo(() => {
    const savedOrder = prefs?.dashboard?.compactHostOrder || []

    if (savedOrder.length === 0 || savedOrder.length !== hosts.length) {
      // No saved order or count mismatch - use default
      return hosts
    }

    // Validate that all IDs exist
    const hostMap = new Map(hosts.map((h) => [h.id, h]))
    const allIdsValid = savedOrder.every((id) => hostMap.has(id))

    if (!allIdsValid) {
      return hosts
    }

    // Apply saved order
    return savedOrder.map((id) => hostMap.get(id)!)
  }, [hosts, prefs?.dashboard?.compactHostOrder])

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

          // Save new order to preferences
          if (hasLoadedPrefs.current) {
            updatePreferences.mutate({
              dashboard: {
                ...prefs?.dashboard,
                compactHostOrder: newOrder,
              }
            })
          }
        }
      }
    },
    [orderedHosts, updatePreferences.mutate, prefs?.dashboard]
  )

  if (isLoading) {
    return <div className="text-muted-foreground">Loading hosts...</div>
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={orderedHosts.map((h) => h.id)} strategy={verticalListSortingStrategy}>
        <div className="flex flex-col gap-2">
          {orderedHosts.map((host) => (
            <SortableCompactHostCard key={host.id} host={host} onHostClick={onHostClick} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  )
}

interface SortableCompactHostCardProps {
  host: Host
  onHostClick: (hostId: string) => void
}

function SortableCompactHostCard({ host, onHostClick }: SortableCompactHostCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: host.id,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    cursor: 'grab',
  }

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <CompactHostCard
        host={{
          id: host.id,
          name: host.name,
          url: host.url,
          status: host.status,
          ...(host.tags && { tags: host.tags }),
        }}
        onClick={() => onHostClick(host.id)}
      />
    </div>
  )
}
