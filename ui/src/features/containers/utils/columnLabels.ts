import type { Column } from '@tanstack/react-table'
import { isCustomColumnId, getColumnLabel as getCustomColumnLabel } from './customColumns'

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
  network: 'Network',
  actions: 'Actions',
}

export function getDisplayColumnLabel<TData>(column: Column<TData, unknown>): string {
  if (isCustomColumnId(column.id)) return getCustomColumnLabel(column.id)
  const header = column.columnDef.header
  return COLUMN_LABELS[column.id] ?? (typeof header === 'string' ? header : column.id)
}
