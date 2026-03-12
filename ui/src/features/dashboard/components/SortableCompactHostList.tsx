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
  DragStartEvent,
  DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { CompactHostCard } from './CompactHostCard'
import { useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'
import { useDndSensors } from '@/features/dashboard/hooks/useDndSensors'
import { debug } from '@/lib/debug'
import type { CompactHost } from '@/features/dashboard/types'

interface SortableCompactHostListProps {
  hosts: CompactHost[]
  onHostClick: (hostId: string) => void
}

export function SortableCompactHostList({ hosts, onHostClick }: SortableCompactHostListProps) {
  const { data: prefs, isLoading } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()
  const hasLoadedPrefs = useRef(false)
  const [isDragging, setIsDragging] = useState(false)
  const frozenHostsRef = useRef<CompactHost[]>([])

  const computedHosts = useMemo(() => {
    const savedOrder = prefs?.dashboard?.compactHostOrder || []

    if (savedOrder.length === 0) {
      debug.log('DnD', 'No saved order, using default host order', { hostCount: hosts.length })
      return hosts
    }

    const hostMap = new Map(hosts.map((h) => [h.id, h]))

    const ordered: CompactHost[] = []
    for (const id of savedOrder) {
      const host = hostMap.get(id)
      if (host) {
        ordered.push(host)
        hostMap.delete(id)
      }
    }
    const hasNewHosts = hostMap.size > 0
    for (const host of hostMap.values()) {
      ordered.push(host)
    }

    if ((hasNewHosts || ordered.length !== hosts.length) && debug.isEnabled()) {
      debug.log('DnD', 'Order reconciled', {
        savedCount: savedOrder.length,
        hostCount: hosts.length,
        resultCount: ordered.length,
        newHosts: [...hostMap.keys()],
      })
    }

    return ordered
  }, [hosts, prefs?.dashboard?.compactHostOrder])

  // Freeze the list during drag to prevent dnd-kit state resets
  const orderedHosts = isDragging ? frozenHostsRef.current : computedHosts

  useEffect(() => {
    if (!isLoading && prefs) {
      hasLoadedPrefs.current = true
    }
  }, [isLoading, prefs])

  const sensors = useDndSensors()

  const handleDragStart = useCallback((event: DragStartEvent) => {
    debug.log('DnD', 'Drag started', { activeId: event.active.id, hostCount: computedHosts.length })
    frozenHostsRef.current = computedHosts
    setIsDragging(true)
  }, [computedHosts])

  const handleDragCancel = useCallback(() => {
    debug.log('DnD', 'Drag cancelled')
    setIsDragging(false)
  }, [])

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setIsDragging(false)

      const { active, over } = event
      debug.log('DnD', 'Drag ended', { activeId: active.id, overId: over?.id ?? null })

      if (over && active.id !== over.id) {
        const oldIndex = frozenHostsRef.current.findIndex((h) => h.id === active.id)
        const newIndex = frozenHostsRef.current.findIndex((h) => h.id === over.id)

        if (oldIndex !== -1 && newIndex !== -1) {
          const newHosts = arrayMove(frozenHostsRef.current, oldIndex, newIndex)
          const newOrder = newHosts.map((h) => h.id)

          debug.log('DnD', 'Saving new order', { oldIndex, newIndex, order: newOrder })

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
  host: CompactHost
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
      <div
        {...attributes}
        {...listeners}
        className="absolute right-0 top-0 h-full cursor-grab active:cursor-grabbing"
        style={{ width: 'min(calc(100% - 200px), 60%)', zIndex: 10 }}
        title="Drag to reorder"
      />
      <CompactHostCard
        host={host}
        onClick={() => onHostClick(host.id)}
      />
    </div>
  )
}
