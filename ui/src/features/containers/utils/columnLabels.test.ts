import { describe, it, expect } from 'vitest'
import type { Column } from '@tanstack/react-table'
import { getDisplayColumnLabel } from './columnLabels'

const column = (id: string, header?: unknown) => ({ id, columnDef: { header } }) as unknown as Column<unknown, unknown>

describe('getDisplayColumnLabel', () => {
  it('names built-in columns whose header is a render function', () => {
    expect(getDisplayColumnLabel(column('host_id', () => null))).toBe('Host')
  })

  it('names custom label/env columns by their key', () => {
    expect(getDisplayColumnLabel(column('label:com.example.tier'))).toBe('LABEL: com.example.tier')
  })

  it('falls back to a string header, then the id', () => {
    expect(getDisplayColumnLabel(column('extra', 'Extra'))).toBe('Extra')
    expect(getDisplayColumnLabel(column('mystery', () => null))).toBe('mystery')
  })
})
