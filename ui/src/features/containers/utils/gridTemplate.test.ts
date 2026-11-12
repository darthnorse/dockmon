import { describe, it, expect } from 'vitest'
import { buildGridTemplate } from './gridTemplate'

const col = (id: string, size: number) => ({ id, getSize: () => size })

describe('buildGridTemplate', () => {
  it('keeps small columns fixed and lets wide ones share leftover space', () => {
    expect(buildGridTemplate([col('select', 50), col('name', 150)], {})).toBe('50px minmax(150px, 1fr)')
  })

  it('fixes a user-resized column at its width', () => {
    expect(buildGridTemplate([col('name', 320), col('image', 150)], { name: 320 })).toBe(
      '320px minmax(150px, 1fr)',
    )
  })

  it('uses the clamped column size, not the stored value', () => {
    expect(buildGridTemplate([col('name', 80)], { name: 30 })).toBe('80px')
  })
})
