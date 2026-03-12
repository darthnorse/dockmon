/**
 * SortableCompactHostList - Drag-and-drop sortable compact host list
 *
 * FEATURES:
 * - Vertical drag-and-drop reordering
 * - Persistent host order
 * - Visual feedback during drag
 * - Uses @dnd-kit for smooth drag experience
 */

import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragStartEvent,
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
  const [isDragging, setIsDragging] = useState(false)
  const frozenHostsRef = useRef<Host[]>([])

  const computedHosts = useMemo(() => {
    const savedOrder = prefs?.dashboard?.compactHostOrder || []

    if (savedOrder.length === 0) {
      return hosts
    }

    const hostMap = new Map(hosts.map((h) => [h.id, h]))

    // Preserve known IDs from saved order, append any new hosts at the end
    const ordered: Host[] = []
    for (const id of savedOrder) {
      const host = hostMap.get(id)
      if (host) {
        ordered.push(host)
        hostMap.delete(id)
      }
    }
    // Append hosts not in saved order (newly added)
    for (const host of hostMap.values()) {
      ordered.push(host)
    }

    return ordered
  }, [hosts, prefs?.dashboard?.compactHostOrder])

  // Freeze the list during drag to prevent dnd-kit state resets
  const orderedHosts = isDragging ? frozenHostsRef.current : computedHosts

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

  const handleDragStart = useCallback((_event: DragStartEvent) => {
    frozenHostsRef.current = computedHosts
    setIsDragging(true)
  }, [computedHosts])

  const handleDragCancel = useCallback(() => {
    setIsDragging(false)
  }, [])

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setIsDragging(false)

      const { active, over } = event

      if (over && active.id !== over.id) {
        const oldIndex = frozenHostsRef.current.findIndex((h) => h.id === active.id)
        const newIndex = frozenHostsRef.current.findIndex((h) => h.id === over.id)

        if (oldIndex !== -1 && newIndex !== -1) {
          const newHosts = arrayMove(frozenHostsRef.current, oldIndex, newIndex)
          const newOrder = newHosts.map((h) => h.id)

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
    [updatePreferences.mutate, prefs?.dashboard]
  )

  if (isLoading) {
    return <div className="text-muted-foreground">Loading hosts...</div>
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragStart={handleDragStart} onDragEnd={handleDragEnd} onDragCancel={handleDragCancel}>
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
  }

  return (
    <div ref={setNodeRef} style={style} className="relative">
      {/* Drag handle overlay - covers right side only */}
      <div
        {...attributes}
        {...listeners}
        className="absolute right-0 top-0 h-full cursor-grab active:cursor-grabbing"
        style={{ width: 'min(calc(100% - 200px), 60%)', zIndex: 10 }}
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
        onClick={() => onHostClick(host.id)}
      />
    </div>
  )
}
