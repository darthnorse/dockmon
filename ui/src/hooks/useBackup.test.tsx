import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ApiError, apiClient } from '@/lib/api/client'
import { useStageBackup } from './useBackup'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

describe('useStageBackup', () => {
  it('refreshes backup status after a failure too', async () => {
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    vi.spyOn(apiClient, 'postBinary').mockResolvedValue({ upload_id: 'a'.repeat(32), size: 1 })
    vi.spyOn(apiClient, 'post').mockRejectedValue(new ApiError('A restore is already staged', 409))
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useStageBackup(), { wrapper })
    result.current.mutate({ file: new File(['x'], 'b.dmbak'), passphrase: 'pw', replace: false })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['backup-status'] })
  })
})
