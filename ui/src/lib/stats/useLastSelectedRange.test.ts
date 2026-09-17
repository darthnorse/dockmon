import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useLastSelectedRange, STORAGE_KEY } from './useLastSelectedRange'

describe('useLastSelectedRange', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults to "live" when no value is stored', () => {
    const { result } = renderHook(() => useLastSelectedRange())
    expect(result.current[0]).toBe('live')
  })

  it('reads a valid stored value on mount', () => {
    localStorage.setItem(STORAGE_KEY, '24h')
    const { result } = renderHook(() => useLastSelectedRange())
    expect(result.current[0]).toBe('24h')
  })

  it('falls back to "live" for invalid stored values', () => {
    localStorage.setItem(STORAGE_KEY, 'not-a-range')
    const { result } = renderHook(() => useLastSelectedRange())
    expect(result.current[0]).toBe('live')
  })

  it('persists new value to localStorage on set', () => {
    const { result } = renderHook(() => useLastSelectedRange())
    act(() => {
      result.current[1]('7d')
    })
    expect(result.current[0]).toBe('7d')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('7d')
  })

  it('accepts all valid TimeRange values', () => {
    const { result } = renderHook(() => useLastSelectedRange())
    const ranges = ['live', '1h', '8h', '24h', '7d', '30d'] as const
    for (const r of ranges) {
      act(() => {
        result.current[1](r)
      })
      expect(result.current[0]).toBe(r)
    }
  })

  it('syncs writes across all mounted instances within the same tab', () => {
    // Two concurrently mounted instances (e.g., container modal + host drawer)
    // must observe each other's writes without requiring a remount.
    const a = renderHook(() => useLastSelectedRange())
    const b = renderHook(() => useLastSelectedRange())
    expect(a.result.current[0]).toBe('live')
    expect(b.result.current[0]).toBe('live')

    act(() => {
      a.result.current[1]('7d')
    })

    expect(a.result.current[0]).toBe('7d')
    expect(b.result.current[0]).toBe('7d')
  })

  it('picks up changes made in another tab via storage event', () => {
    const { result } = renderHook(() => useLastSelectedRange())
    expect(result.current[0]).toBe('live')

    act(() => {
      // Simulate a write from a different tab: the browser does NOT fire
      // `storage` events on the tab that performed the write, only on others.
      localStorage.setItem(STORAGE_KEY, '24h')
      window.dispatchEvent(
        new StorageEvent('storage', { key: STORAGE_KEY, newValue: '24h' }),
      )
    })

    expect(result.current[0]).toBe('24h')
  })
})
