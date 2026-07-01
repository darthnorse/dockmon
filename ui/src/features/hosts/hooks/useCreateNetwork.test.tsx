/**
 * Tests for useCreateNetwork.
 *
 * Pins the request contract (POST /hosts/{id}/networks with the network fields)
 * and the success/error toast behavior.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'

import { useCreateNetwork } from './useHostNetworks'
import { apiClient } from '@/lib/api/client'

vi.mock('sonner')
vi.mock('@/lib/api/client')

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe('useCreateNetwork', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('POSTs the network payload to the host networks endpoint', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      id: 'abc123def456',
      name: 'my-net',
      driver: 'bridge',
    })

    const { result } = renderHook(() => useCreateNetwork('host-1'), {
      wrapper: createWrapper(),
    })

    result.current.mutate({
      name: 'my-net',
      driver: 'bridge',
      subnet: '172.30.0.0/16',
      gateway: '172.30.0.1',
      internal: true,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(apiClient.post).toHaveBeenCalledWith('/hosts/host-1/networks', {
      name: 'my-net',
      driver: 'bridge',
      subnet: '172.30.0.0/16',
      gateway: '172.30.0.1',
      internal: true,
    })
    expect(toast.success).toHaveBeenCalled()
  })

  it('surfaces an error toast on failure', async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error('boom'))

    const { result } = renderHook(() => useCreateNetwork('host-1'), {
      wrapper: createWrapper(),
    })

    result.current.mutate({ name: 'x' })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(toast.error).toHaveBeenCalled()
  })
})
