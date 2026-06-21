import { describe, it, expect } from 'vitest'
import { mergeHistoryDelta } from './useStatsHistory'
import type { StatsHistoryResponse } from './historyTypes'

function makeResp(partial: Partial<StatsHistoryResponse>): StatsHistoryResponse {
  return {
    tier: '1h',
    tier_seconds: 3600,
    interval_seconds: 7,
    from: 0,
    to: 0,
    server_time: 0,
    timestamps: [],
    cpu: [],
    mem: [],
    net_bps: [],
    ...partial,
  }
}

describe('mergeHistoryDelta', () => {
  it('keeps optional columns parallel to timestamps when a poll omits them', () => {
    // Cached series carries memory byte columns for every bucket.
    const cached = makeResp({
      from: 100,
      to: 200,
      timestamps: [100, 200],
      cpu: [1, 2],
      mem: [10, 20],
      net_bps: [5, 6],
      memory_used_bytes: [1000, 2000],
      memory_limit_bytes: [8000, 8000],
    })

    // A `since` poll appends a new bucket but OMITS the optional memory columns
    // (the server-contract drift the hardening defends against).
    const next = makeResp({
      from: 300,
      to: 300,
      timestamps: [300],
      cpu: [3],
      mem: [30],
      net_bps: [7],
    })

    const merged = mergeHistoryDelta(cached, next, '1h')

    expect(merged.timestamps).toEqual([100, 200, 300])
    // Without the fix, these arrays stay length 2 and desync from timestamps,
    // so every index-based tooltip/summary read maps to the wrong bucket.
    expect(merged.memory_used_bytes?.length).toBe(merged.timestamps.length)
    expect(merged.memory_limit_bytes?.length).toBe(merged.timestamps.length)
    // The omitted bucket is null-filled, not dropped.
    expect(merged.memory_used_bytes?.[2]).toBeNull()
    expect(merged.memory_limit_bytes?.[2]).toBeNull()
  })

  it('appends optional column values when the poll includes them', () => {
    const cached = makeResp({
      from: 100,
      to: 100,
      timestamps: [100],
      cpu: [1],
      mem: [10],
      net_bps: [5],
      memory_used_bytes: [1000],
      memory_limit_bytes: [8000],
    })
    const next = makeResp({
      from: 200,
      to: 200,
      timestamps: [200],
      cpu: [2],
      mem: [20],
      net_bps: [6],
      memory_used_bytes: [2000],
      memory_limit_bytes: [8000],
    })

    const merged = mergeHistoryDelta(cached, next, '1h')

    expect(merged.timestamps).toEqual([100, 200])
    expect(merged.memory_used_bytes).toEqual([1000, 2000])
    expect(merged.memory_limit_bytes).toEqual([8000, 8000])
  })

  it('backfills nulls when only the new poll carries an optional column', () => {
    // Cached lacks the column entirely; next introduces it mid-session.
    const cached = makeResp({
      from: 100,
      to: 200,
      timestamps: [100, 200],
      cpu: [1, 2],
      mem: [10, 20],
      net_bps: [5, 6],
    })
    const next = makeResp({
      from: 300,
      to: 300,
      timestamps: [300],
      cpu: [3],
      mem: [30],
      net_bps: [7],
      memory_used_bytes: [3000],
      memory_limit_bytes: [8000],
    })

    const merged = mergeHistoryDelta(cached, next, '1h')

    expect(merged.timestamps).toEqual([100, 200, 300])
    // The cached span is backfilled with nulls so the column is parallel.
    expect(merged.memory_used_bytes?.length).toBe(3)
    expect(merged.memory_used_bytes).toEqual([null, null, 3000])
  })

  it('replaces a trailing null "now" bucket on the next poll (regression)', () => {
    // First response includes a trailing bucket whose values are still null.
    const cached = makeResp({
      from: 100,
      to: 200,
      timestamps: [100, 200],
      cpu: [10, null],
      mem: [1, null],
      net_bps: [5, null],
    })
    // A later poll returns the SAME timestamp now filled in.
    const next = makeResp({
      from: 200,
      to: 200,
      timestamps: [200],
      cpu: [20],
      mem: [2],
      net_bps: [6],
    })

    const merged = mergeHistoryDelta(cached, next, '1h')

    expect(merged.timestamps).toEqual([100, 200])
    expect(merged.cpu).toEqual([10, 20])
    expect(merged.mem).toEqual([1, 2])
  })
})
