import {
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { sortableKeyboardCoordinates, type useSortable } from '@dnd-kit/sortable'

export function useDndSensors() {
  return useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )
}

export type DragHandleProps = Pick<ReturnType<typeof useSortable>, 'attributes' | 'listeners'>
