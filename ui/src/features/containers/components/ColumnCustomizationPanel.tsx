/**
 * Column Customization Panel
 *
 * Provides UI for customizing table columns:
 * - Toggle column visibility (show/hide columns)
 * - Reorder columns via drag-and-drop
 *
 * Integrates with TanStack Table v8 and user preferences API
 */

import { useState } from 'react'
import type { Table } from '@tanstack/react-table'
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useDndSensors } from '@/features/dashboard/hooks/useDndSensors'
import { Settings, GripVertical, Eye, EyeOff, RotateCcw, Trash2, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu } from '@/components/ui/dropdown-menu'
import { isCustomColumnId, getColumnLabel as getCustomColumnLabel } from '../utils/customColumns'
import { useUserPreferences, useUpdatePreferences } from '@/lib/hooks/useUserPreferences'
import { AddCustomColumnDialog } from './AddCustomColumnDialog'

interface ColumnCustomizationPanelProps<TData> {
  table: Table<TData>
}

function SortableColumnItem({
  id,
  label,
  isVisible,
  onToggleVisibility,
  canHide,
  onRemove,
}: {
  id: string
  label: string
  isVisible: boolean
  onToggleVisibility: () => void
  canHide: boolean
  // Note: typed as union with undefined (not `?:`) so callers can pass
  // `onRemove={cond ? fn : undefined}` cleanly under exactOptionalPropertyTypes.
  onRemove: (() => void) | undefined
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-2 px-2 py-1.5 bg-surface-1 border border-border rounded hover:bg-surface-2 transition-colors"
    >
      <button
        {...attributes}
        {...listeners}
        className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
        title="Drag to reorder"
      >
        <GripVertical className="h-4 w-4" />
      </button>

      <span className="flex-1 text-sm text-foreground">{label}</span>

      <button
        onClick={onToggleVisibility}
        disabled={!canHide}
        className={`${
          canHide
            ? 'text-muted-foreground hover:text-foreground'
            : 'text-muted-foreground/30 cursor-not-allowed'
        }`}
        title={canHide ? (isVisible ? 'Hide column' : 'Show column') : 'Cannot hide this column'}
      >
        {isVisible ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
      </button>

      {onRemove && (
        <button
          onClick={onRemove}
          className="text-muted-foreground hover:text-destructive"
          title="Remove custom column"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}

// Maps column IDs to display names
const COLUMN_LABELS: Record<string, string> = {
  state: 'Status',
  name: 'Name',
  policy: 'Policy',
  alerts: 'Alerts',
  host_id: 'Host',
  ports: 'Ports',
  created: 'Uptime',
  cpu: 'CPU %',
  memory: 'RAM',
  actions: 'Actions',
}

export function ColumnCustomizationPanel<TData>({ table }: ColumnCustomizationPanelProps<TData>) {
  const allColumns = table.getAllLeafColumns().filter(
    (column) => column.id !== 'select'
  )

  const columnOrder = table.getState().columnOrder
  const currentOrder = columnOrder.length > 0
    ? columnOrder.filter(id => id !== 'select')
    : allColumns.map((c) => c.id)

  // Include saved order + any new columns not yet in preferences
  const orderedColumns = currentOrder.length > 0
    ? [
        ...currentOrder
          .map((id) => allColumns.find((col) => col.id === id))
          .filter((col): col is NonNullable<typeof col> => col !== undefined),
        ...allColumns.filter((col) => !currentOrder.includes(col.id))
      ]
    : allColumns

  const sensors = useDndSensors()

  const { data: preferences } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()

  const [addDialogOpen, setAddDialogOpen] = useState(false)

  const handleAddCustomColumn = (columnId: string) => {
    const currentOrder = preferences?.container_table_column_order ?? []
    const currentVisibility = preferences?.container_table_column_visibility ?? {}
    updatePreferences.mutate({
      container_table_column_order: [...currentOrder, columnId],
      container_table_column_visibility: { ...currentVisibility, [columnId]: true },
    })
  }

  const handleRemoveCustomColumn = (columnId: string) => {
    const newOrder = (preferences?.container_table_column_order ?? []).filter(
      (id: string) => id !== columnId
    )
    const visibility = { ...(preferences?.container_table_column_visibility ?? {}) }
    delete visibility[columnId]
    updatePreferences.mutate({
      container_table_column_order: newOrder,
      container_table_column_visibility: visibility,
    })
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event

    if (over && active.id !== over.id) {
      const orderedColumnIds = orderedColumns.map(c => c.id)
      const oldIndex = orderedColumnIds.indexOf(active.id as string)
      const newIndex = orderedColumnIds.indexOf(over.id as string)

      const newOrder = arrayMove(orderedColumnIds, oldIndex, newIndex)
      table.setColumnOrder(['select', ...newOrder])
    }
  }

  const handleToggleVisibility = (columnId: string) => {
    const column = table.getColumn(columnId)
    if (column) {
      column.toggleVisibility(!column.getIsVisible())
    }
  }

  const handleResetColumns = () => {
    allColumns.forEach((column) => {
      column.toggleVisibility(true)
    })
    table.setColumnOrder([])
  }

  const visibleCount = allColumns.filter((col) => col.getIsVisible()).length

  return (
    <DropdownMenu
      trigger={
        <Button variant="outline" size="sm" className="h-9">
          <Settings className="h-3.5 w-3.5 mr-2" />
          Columns
        </Button>
      }
      align="end"
    >
      <div className="min-w-[280px] max-w-[320px]" onClick={(e) => e.stopPropagation()}>
        <div className="px-3 py-2 border-b border-border">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Customize Columns</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleResetColumns}
              className="h-7 text-xs"
            >
              <RotateCcw className="h-3 w-3 mr-1" />
              Reset
            </Button>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {visibleCount} of {allColumns.length} visible
          </p>
        </div>

        <div className="px-3 py-3 max-h-[400px] overflow-y-auto">
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={orderedColumns.map((col) => col.id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="space-y-1.5">
                {orderedColumns.map((column) => {
                  const canHide = visibleCount > 1 || !column.getIsVisible()

                  const label = isCustomColumnId(column.id)
                    ? getCustomColumnLabel(column.id)
                    : (COLUMN_LABELS[column.id] ??
                        (typeof column.columnDef.header === 'string'
                          ? column.columnDef.header
                          : column.id))

                  return (
                    <SortableColumnItem
                      key={column.id}
                      id={column.id}
                      label={label}
                      isVisible={column.getIsVisible()}
                      onToggleVisibility={() => handleToggleVisibility(column.id)}
                      canHide={canHide}
                      onRemove={isCustomColumnId(column.id)
                        ? () => handleRemoveCustomColumn(column.id)
                        : undefined}
                    />
                  )
                })}
              </div>
            </SortableContext>
          </DndContext>
        </div>

        <div className="px-3 py-2 border-t border-border">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAddDialogOpen(true)}
            className="w-full justify-start text-sm"
          >
            <Plus className="h-3.5 w-3.5 mr-2" />
            Add custom column…
          </Button>
        </div>

        <AddCustomColumnDialog
          open={addDialogOpen}
          existingColumnIds={allColumns.map(c => c.id)}
          onOpenChange={setAddDialogOpen}
          onAdd={handleAddCustomColumn}
        />

        <div className="px-3 py-2 border-t border-border bg-muted/30">
          <p className="text-xs text-muted-foreground">
            Drag rows to reorder columns. Click the eye icon to show/hide.
          </p>
        </div>
      </div>
    </DropdownMenu>
  )
}
