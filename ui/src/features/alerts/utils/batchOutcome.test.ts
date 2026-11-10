import { describe, expect, it } from 'vitest'
import { describeBatchOutcome } from './batchOutcome'

describe('describeBatchOutcome', () => {
  it('returns null when every alert changed', () => {
    expect(describeBatchOutcome({ resolved: ['a', 'b'], skipped: [], not_found: [] })).toBeNull()
  })

  it('reports skipped and missing alerts for resolve', () => {
    expect(
      describeBatchOutcome({
        resolved: ['a'],
        skipped: [{ id: 'b', reason: 'already_resolved' }],
        not_found: ['c', 'd'],
      }),
    ).toBe('1 alert resolved; 1 already resolved, 2 no longer available')
  })

  it('uses the snooze verb for snooze results', () => {
    expect(
      describeBatchOutcome({ snoozed: ['a', 'b'], skipped: [{ id: 'c', reason: 'resolved' }], not_found: [] }),
    ).toBe('2 alerts snoozed; 1 already resolved')
  })
})
