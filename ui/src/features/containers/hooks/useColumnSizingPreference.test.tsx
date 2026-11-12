import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode } from 'react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { useColumnSizingPreference } from './useColumnSizingPreference'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/api/client', () => ({
  apiClient: {
    get: vi.fn(),
    patch: vi.fn(),
  },
}))

const LONG_LABEL_COLUMN = `label:${'x'.repeat(140)}`
const COLUMN_IDS = ['name', 'image', 'ports', LONG_LABEL_COLUMN]

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

describe('useColumnSizingPreference', () => {
  let queryClient: QueryClient
  let wrapper: ({ children }: { children: ReactNode }) => JSX.Element
  let stored: Record<string, number> | null

  beforeEach(() => {
    vi.clearAllMocks()
    stored = { name: 300 }
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    wrapper = ({ children }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    vi.mocked(apiClient.get).mockImplementation(async () => ({ container_table_column_sizing: stored }))
    vi.mocked(apiClient.patch).mockImplementation(async (_url, body) => {
      stored = (body as { container_table_column_sizing: Record<string, number> }).container_table_column_sizing
      return { status: 'ok' }
    })
  })

  const render = () => renderHook(() => useColumnSizingPreference(COLUMN_IDS), { wrapper })

  it('hydrates from stored preferences without saving them back', async () => {
    const { result } = render()

    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300 }))
    expect(apiClient.patch).not.toHaveBeenCalled()
  })

  it('does not save while the user is dragging', async () => {
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300 }))

    act(() => result.current.setColumnSizing({ name: 350 }))

    expect(result.current.columnSizing).toEqual({ name: 350 })
    expect(apiClient.patch).not.toHaveBeenCalled()
  })

  it('saves once when a resize is committed', async () => {
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300 }))

    act(() => result.current.commitColumnWidth('name', 410))

    expect(result.current.columnSizing).toEqual({ name: 410 })
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1))
    expect(apiClient.patch).toHaveBeenCalledWith('/v2/user/preferences', {
      container_table_column_sizing: { name: 410 },
    })
  })

  it('drops widths for columns that no longer exist', async () => {
    stored = { name: 300, 'label:gone': 200 }
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300, 'label:gone': 200 }))

    act(() => result.current.commitColumnWidth('name', 410))

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1))
    expect(apiClient.patch).toHaveBeenCalledWith('/v2/user/preferences', {
      container_table_column_sizing: { name: 410 },
    })
  })

  it('serializes saves and sends only the latest pending width', async () => {
    const first = deferred<unknown>()
    vi.mocked(apiClient.patch).mockImplementationOnce(async (_url, body) => {
      await first.promise
      stored = (body as { container_table_column_sizing: Record<string, number> }).container_table_column_sizing
      return { status: 'ok' }
    })
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300 }))

    act(() => result.current.commitColumnWidth('name', 310))
    act(() => result.current.commitColumnWidth('name', 320))
    act(() => result.current.commitColumnWidth('name', 330))
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1))

    await act(async () => first.resolve(undefined))

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2))
    expect(vi.mocked(apiClient.patch).mock.calls[1]?.[1]).toEqual({ container_table_column_sizing: { name: 330 } })
    await waitFor(() => expect(stored).toEqual({ name: 330 }))
    expect(result.current.columnSizing).toEqual({ name: 330 })
  })

  it('does not let a refetch of an older save overwrite a newer local width', async () => {
    const first = deferred<unknown>()
    vi.mocked(apiClient.patch).mockImplementationOnce(async () => {
      await first.promise
      stored = { name: 310 }
      return { status: 'ok' }
    })
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300 }))

    act(() => result.current.commitColumnWidth('name', 310))
    act(() => result.current.setColumnSizing({ name: 500 }))
    await act(async () => first.resolve(undefined))
    await act(async () => {
      await queryClient.refetchQueries()
    })

    expect(result.current.columnSizing).toEqual({ name: 500 })
  })

  it('resets every width', async () => {
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300 }))

    act(() => result.current.resetColumnSizing())

    expect(result.current.columnSizing).toEqual({})
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith('/v2/user/preferences', { container_table_column_sizing: {} }),
    )
  })

  it('removes a single column width', async () => {
    stored = { name: 300, image: 200 }
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300, image: 200 }))

    act(() => result.current.commitColumnWidth('image', null))

    expect(result.current.columnSizing).toEqual({ name: 300 })
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith('/v2/user/preferences', {
        container_table_column_sizing: { name: 300 },
      }),
    )
  })

  it('keeps a column id the backend would reject out of the saved map', async () => {
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300 }))

    act(() => result.current.commitColumnWidth(LONG_LABEL_COLUMN, 250))

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1))
    expect(apiClient.patch).toHaveBeenCalledWith('/v2/user/preferences', {
      container_table_column_sizing: { name: 300 },
    })
  })

  it('tells the user when widths could not be saved', async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(new Error('422'))
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300 }))

    act(() => result.current.commitColumnWidth('name', 410))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Could not save column widths'))
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300 }))
  })

  it('treats maps with the same widths in a different key order as equal', async () => {
    stored = { name: 300, image: 200 }
    const { result } = render()
    await waitFor(() => expect(result.current.columnSizing).toEqual({ name: 300, image: 200 }))

    const before = result.current.columnSizing
    stored = { image: 200, name: 300 }
    await act(async () => {
      await queryClient.refetchQueries()
    })

    expect(result.current.columnSizing).toBe(before)
  })
})
