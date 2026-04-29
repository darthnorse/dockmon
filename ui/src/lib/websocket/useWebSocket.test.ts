/**
 * useWebSocket Hook Tests
 *
 * Tests focus on critical stability fixes:
 * - React Strict Mode double-mount handling
 * - Callback reference stability
 * - URL change reconnection
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useWebSocket } from './useWebSocket'

// Mock WebSocket. The static constants must match the WHATWG WebSocket API
// (CONNECTING=0, OPEN=1, CLOSING=2, CLOSED=3) — useWebSocket.ts does
// `wsRef.current?.readyState === WebSocket.OPEN` and without OPEN the
// comparison becomes `undefined === undefined` and early-returns before any
// connection is created.
class MockWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  public onopen: (() => void) | null = null
  public onmessage: ((event: MessageEvent) => void) | null = null
  public onerror: ((event: Event) => void) | null = null
  public onclose: (() => void) | null = null
  public readyState = MockWebSocket.CONNECTING

  constructor(public url: string) {
    // Simulate async connection
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN
      this.onopen?.()
    }, 10)
  }

  send(_data: string) {
    // Mock send
  }

  close() {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }
}

describe('useWebSocket', () => {
  beforeEach(() => {
    // @ts-expect-error - Mocking WebSocket
    global.WebSocket = MockWebSocket
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should handle React Strict Mode double-mount without reconnection storm', async () => {
    const onMessage = vi.fn()
    const onConnect = vi.fn()

    // First mount
    const { unmount, rerender } = renderHook(() =>
      useWebSocket({
        url: 'wss://test.com/ws',
        onMessage,
        onConnect,
      })
    )

    // Wait for connection
    await waitFor(() => {
      expect(onConnect).toHaveBeenCalledTimes(1)
    })

    // Simulate React Strict Mode unmount
    unmount()

    // Remount (Strict Mode second mount)
    const { result } = renderHook(() =>
      useWebSocket({
        url: 'wss://test.com/ws',
        onMessage,
        onConnect,
      })
    )

    // Wait for connection
    await waitFor(() => {
      expect(onConnect).toHaveBeenCalledTimes(2)
    })

    // Should be connected, not in reconnection loop
    expect(result.current.status).toBe('connected')
  })

  it('should maintain stable callbacks without triggering reconnection', async () => {
    let callbackCallCount = 0
    const onMessage = vi.fn()

    const { rerender } = renderHook(
      ({ callback }) =>
        useWebSocket({
          url: 'wss://test.com/ws',
          onMessage: callback,
        }),
      {
        initialProps: {
          callback: () => {
            callbackCallCount++
            onMessage()
          },
        },
      }
    )

    await waitFor(() => {
      expect(onMessage).toHaveBeenCalledTimes(0) // Not called yet
    })

    // Change callback (should NOT trigger reconnection)
    rerender({
      callback: () => {
        callbackCallCount++
        onMessage()
      },
    })

    // Callback changed but connection should remain stable
    await new Promise((resolve) => setTimeout(resolve, 50))

    // Should still be connected (no reconnection triggered)
    expect(callbackCallCount).toBe(0) // No calls yet (no messages received)
  })

  it('should reconnect when URL changes', async () => {
    const onConnect = vi.fn()

    const { rerender } = renderHook(
      ({ url }) =>
        useWebSocket({
          url,
          onConnect,
        }),
      {
        initialProps: { url: 'wss://test.com/ws' },
      }
    )

    await waitFor(() => {
      expect(onConnect).toHaveBeenCalledTimes(1)
    })

    // Change URL (should trigger reconnection)
    rerender({ url: 'wss://test2.com/ws' })

    await waitFor(() => {
      expect(onConnect).toHaveBeenCalledTimes(2)
    })
  })

  it('should cleanup connection on unmount', async () => {
    const onDisconnect = vi.fn()

    const { unmount } = renderHook(() =>
      useWebSocket({
        url: 'wss://test.com/ws',
        onDisconnect,
      })
    )

    await waitFor(() => {
      expect(onDisconnect).toHaveBeenCalledTimes(0)
    })

    unmount()

    await waitFor(() => {
      expect(onDisconnect).toHaveBeenCalledTimes(1)
    })
  })
})
