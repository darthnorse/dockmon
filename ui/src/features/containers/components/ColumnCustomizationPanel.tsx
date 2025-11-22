/**
 * Column Customization Panel
 *
 * Provides UI for customizing table columns:
 * - Toggle column visibility (show/hide columns)
 * - Reorder columns via drag-and-drop
 *
 * Integrates with TanStack Table v8 and user preferences API
 */

import type { Table } from '@tanstack/react-table'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Settings, GripVertical, Eye, EyeOff, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu } from '@/components/ui/dropdown-menu'

interface ColumnCustomizationPanelProps<TData> {
  table: Table<TData>
}

/**
 * Sortable column item for drag-and-drop reordering
 */
function SortableColumnItem({
  id,
  label,
  isVisible,
  onToggleVisibility,
  canHide,
}: {
  id: string
  label: string
  isVisible: boolean
  onToggleVisibility: () => void
  canHide: boolean
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
      {/* Drag handle */}
      <button
        {...attributes}
        {...listeners}
        className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
        title="Drag to reorder"
      >
        <GripVertical className="h-4 w-4" />
      </button>

      {/* Column label */}
      <span className="flex-1 text-sm text-foreground">{label}</span>

      {/* Visibility toggle */}
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
    </div>
  )
}

/**
 * Column Customization Panel Component
 *
 * Features:
 * - Show/hide columns with checkboxes
 * - Reorder columns with drag-and-drop
 * - Reset to defaults button
 */
// Friendly column labels (maps column IDs to display names)
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
  // Get all columns (excluding only the select checkbox - users need that for bulk actions)
  const allColumns = table.getAllLeafColumns().filter(
    (column) => column.id !== 'select'
  )

  // Get current column order from table state (excludes 'select' which is always first)
  const columnOrder = table.getState().columnOrder
  const currentOrder = columnOrder.length > 0
    ? columnOrder.filter(id => id !== 'select') // Remove 'select' if present
    : allColumns.map((c) => c.id)

  // Reorder columns for display
  // Include both saved order AND new columns not in saved order (future-proof for new columns)
  const orderedColumns = currentOrder.length > 0
    ? [
        // Columns in saved order
        ...currentOrder
          .map((id) => allColumns.find((col) => col.id === id))
          .filter((col): col is NonNullable<typeof col> => col !== undefined),
        // New columns not in saved order (added after user customized)
        ...allColumns.filter((col) => !currentOrder.includes(col.id))
      ]
    : allColumns

  // Drag and drop sensors
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event

    if (over && active.id !== over.id) {
      // Use orderedColumns (what user sees) instead of currentOrder (saved state)
      // This allows dragging of newly added columns that aren't in saved preferences yet
      const orderedColumnIds = orderedColumns.map(c => c.id)
      const oldIndex = orderedColumnIds.indexOf(active.id as string)
      const newIndex = orderedColumnIds.indexOf(over.id as string)

      const newOrder = arrayMove(orderedColumnIds, oldIndex, newIndex)
      // Always prepend 'select' so it stays on the left
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
    // Reset visibility to defaults (all visible)
    allColumns.forEach((column) => {
      column.toggleVisibility(true)
    })

    // Reset order to default (empty array means use natural column definition order)
    // Note: Empty array will use the order columns are defined in, which has 'select' first
    table.setColumnOrder([])
  }

  // Count visible columns
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
        {/* Header */}
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

        {/* Column list with drag-and-drop */}
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
                  // Determine if column can be hidden (at least one column must be visible)
                  const canHide = visibleCount > 1 || !column.getIsVisible()

                  // Get column label from mapping or fallback to capitalized ID
                  const label = COLUMN_LABELS[column.id] ||
                    (typeof column.columnDef.header === 'string'
                      ? column.columnDef.header
                      : column.id.charAt(0).toUpperCase() + column.id.slice(1))

                  return (
                    <SortableColumnItem
                      key={column.id}
                      id={column.id}
                      label={label}
                      isVisible={column.getIsVisible()}
                      onToggleVisibility={() => handleToggleVisibility(column.id)}
                      canHide={canHide}
                    />
                  )
                })}
              </div>
            </SortableContext>
          </DndContext>
        </div>

        {/* Instructions */}
        <div className="px-3 py-2 border-t border-border bg-muted/30">
          <p className="text-xs text-muted-foreground">
            Drag rows to reorder columns. Click the eye icon to show/hide.
          </p>
        </div>
      </div>
    </DropdownMenu>
  )
}
