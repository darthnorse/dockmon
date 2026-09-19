/**
 * The IP column sorted through real TanStack sorting, not just the comparator.
 *
 * The comparator alone cannot show where "Not connected" rows land, because
 * the table inverts a comparator's result for descending. sortUndefined is
 * applied before that inversion, which is what keeps blanks at the bottom in
 * both directions - a detail worth pinning, since it lives in table internals.
 */
import { describe, it, expect } from 'vitest'
import {
  createColumnHelper,
  getCoreRowModel,
  getSortedRowModel,
  createTable,
  type SortingState,
} from '@tanstack/react-table'

import { compareIpAddresses } from './ipSort'

interface Row {
  name: string
  docker_ip?: string | null
}

const rows: Row[] = [
  { name: 'c-10', docker_ip: '192.168.1.10' },
  { name: 'c-none', docker_ip: null },
  { name: 'c-9', docker_ip: '192.168.1.9' },
  { name: 'c-8', docker_ip: '192.168.1.8' },
  { name: 'c-11', docker_ip: '192.168.1.11' },
]

const helper = createColumnHelper<Row>()

const columns = [
  helper.accessor((row) => row.docker_ip ?? undefined, {
    id: 'ip',
    sortUndefined: 'last' as const,
    sortingFn: (a, b) => compareIpAddresses(a.original.docker_ip, b.original.docker_ip),
  }),
]

function orderBy(sorting: SortingState): string[] {
  let state = { sorting }
  const table = createTable<Row>({
    data: rows,
    columns,
    state,
    onStateChange: (updater) => {
      state = typeof updater === 'function' ? updater(state as never) : updater
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    renderFallbackValue: null,
  })
  table.setOptions((prev) => ({ ...prev, state: { ...prev.state, sorting } }))
  return table.getSortedRowModel().rows.map((r) => r.original.name)
}

describe('IP column sorting', () => {
  it('ascends numerically with unaddressed containers last', () => {
    expect(orderBy([{ id: 'ip', desc: false }])).toEqual([
      'c-8',
      'c-9',
      'c-10',
      'c-11',
      'c-none',
    ])
  })

  it('descends numerically and still keeps unaddressed containers last', () => {
    expect(orderBy([{ id: 'ip', desc: true }])).toEqual([
      'c-11',
      'c-10',
      'c-9',
      'c-8',
      'c-none',
    ])
  })
})
