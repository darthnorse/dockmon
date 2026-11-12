import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { toast } from 'sonner'
import { EnvVarList } from './EnvVarList'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

const LONG_VALUE = 'postgres://app:secret@db.internal:5432/' + 'x'.repeat(300)

describe('EnvVarList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows long values in full, wrapping instead of truncating', () => {
    render(<EnvVarList entries={[['DATABASE_URL', LONG_VALUE]]} />)

    const value = screen.getByText(LONG_VALUE)
    expect(value).not.toHaveClass('truncate')
    expect(value).toHaveClass('break-all')
  })

  it('renders duplicate keys as separate rows', () => {
    render(
      <EnvVarList
        entries={[
          ['PATH', '/usr/bin'],
          ['PATH', '/opt/bin'],
        ]}
      />,
    )

    expect(screen.getByText('/usr/bin')).toBeInTheDocument()
    expect(screen.getByText('/opt/bin')).toBeInTheDocument()
  })

  it('copies a value to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<EnvVarList entries={[['DATABASE_URL', LONG_VALUE]]} />)

    fireEvent.click(screen.getByRole('button', { name: 'Copy value of DATABASE_URL' }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(LONG_VALUE))
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('reports when the clipboard is unavailable', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    render(<EnvVarList entries={[['DATABASE_URL', 'x']]} />)

    fireEvent.click(screen.getByRole('button', { name: 'Copy value of DATABASE_URL' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
  })

  it('reports when the clipboard write fails', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<EnvVarList entries={[['DATABASE_URL', 'x']]} />)

    fireEvent.click(screen.getByRole('button', { name: 'Copy value of DATABASE_URL' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
  })
})
