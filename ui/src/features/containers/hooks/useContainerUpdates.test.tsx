import { describe, it, expect, vi } from 'vitest'
import type { ReactNode } from 'react'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useCheckAllUpdates, useCheckContainerUpdate } from './useContainerUpdates'

vi.mock('@/lib/api/client', () => ({
  apiClient: { post: vi.fn().mockResolvedValue({}) },
}))

function setup<T>(useHook: () => T) {
  const queryClient = new QueryClient()
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return { result: renderHook(useHook, { wrapper }).result, invalidate }
}

describe('update checks refresh the container table marker', () => {
  it('after a single check', async () => {
    const { result, invalidate } = setup(useCheckContainerUpdate)

    await result.current.mutateAsync({ hostId: 'host-1', containerId: 'abc123def456' })

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['all-auto-update-configs'] })
  })

  it('after checking all', async () => {
    const { result, invalidate } = setup(useCheckAllUpdates)

    await result.current.mutateAsync()

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['all-auto-update-configs'] })
  })
})
