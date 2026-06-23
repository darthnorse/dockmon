import { describe, it, expect } from 'vitest'
import { appendLiveTick, type LiveTick } from './useLiveHistory'
import type { LiveStatsResponse } from './historyTypes'

function makeSeries(partial: Partial<LiveStatsResponse>): LiveStatsResponse {
  return {
    timestamps: [],
    cpu: [],
    mem: [],
    net: [],
    memory_used_bytes: [],
    memory_limit_bytes: [],
    ...partial,
  }
}

function makeTick(partial: Partial<LiveTick>): LiveTick {
  return {
    timestamp: 0,
    cpu: 0,
    mem: 0,
    net: 0,
    memory_used_bytes: null,
    memory_limit_bytes: null,
    ...partial,
  }
}

describe('appendLiveTick', () => {
  it('appends a newer tick to every column, parallel to timestamps', () => {
    const series = makeSeries({
      timestamps: [100, 102],
      cpu: [1, 2],
      mem: [10, 20],
      net: [5, 6],
      memory_used_bytes: [1000, 1100],
      memory_limit_bytes: [8000, 8000],
    })
    const out = appendLiveTick(
      series,
      makeTick({ timestamp: 104, cpu: 3, mem: 30, net: 7, memory_used_bytes: 1200, memory_limit_bytes: 8000 }),
      600,
    )
    expect(out.timestamps).toEqual([100, 102, 104])
    expect(out.cpu).toEqual([1, 2, 3])
    expect(out.mem).toEqual([10, 20, 30])
    expect(out.net).toEqual([5, 6, 7])
    expect(out.memory_used_bytes).toEqual([1000, 1100, 1200])
    expect(out.memory_limit_bytes).toEqual([8000, 8000, 8000])
  })

  it('ignores a tick whose timestamp is not newer than the last point', () => {
    const series = makeSeries({
      timestamps: [100, 102],
      cpu: [1, 2], mem: [10, 20], net: [5, 6],
      memory_used_bytes: [1000, 1100], memory_limit_bytes: [8000, 8000],
    })
    // Same timestamp as the last point: stale/duplicate broadcast -> no-op.
    const same = appendLiveTick(series, makeTick({ timestamp: 102, cpu: 9 }), 600)
    expect(same.timestamps).toEqual([100, 102])
    expect(same.cpu).toEqual([1, 2])
    // Older timestamp (out of order) -> also a no-op.
    const older = appendLiveTick(series, makeTick({ timestamp: 50, cpu: 9 }), 600)
    expect(older.timestamps).toEqual([100, 102])
  })

  it('trims points older than the window relative to the newest timestamp', () => {
    const series = makeSeries({
      timestamps: [100, 700, 1200],
      cpu: [1, 2, 3], mem: [10, 20, 30], net: [5, 6, 7],
      memory_used_bytes: [1000, 1100, 1200], memory_limit_bytes: [8000, 8000, 8000],
    })
    // Window 600s; new tick at 1300 -> cutoff 700, so the t=100 point drops.
    const out = appendLiveTick(
      series,
      makeTick({ timestamp: 1300, cpu: 4, mem: 40, net: 8, memory_used_bytes: 1300, memory_limit_bytes: 8000 }),
      600,
    )
    expect(out.timestamps).toEqual([700, 1200, 1300])
    expect(out.cpu).toEqual([2, 3, 4])
    expect(out.memory_used_bytes).toEqual([1100, 1200, 1300])
  })

  it('seeds an empty series with the first tick', () => {
    const out = appendLiveTick(
      makeSeries({}),
      makeTick({ timestamp: 500, cpu: 1, mem: 2, net: 3, memory_used_bytes: 10, memory_limit_bytes: 20 }),
      600,
    )
    expect(out.timestamps).toEqual([500])
    expect(out.cpu).toEqual([1])
    expect(out.memory_used_bytes).toEqual([10])
  })
})
