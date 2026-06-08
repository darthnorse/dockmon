/**
 * Tests for ContainerLinkList.
 *
 * Regression guard: the list must render EVERY attached container as a
 * clickable button (no "+N more" truncation), so users can open the modal
 * for any container on a busy network like the default bridge or host.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@/test/utils'

import { ContainerLinkList } from './ContainerLinkList'

const openModal = vi.fn()

// Replace the provider with a passthrough + spy hook so we can assert exactly
// which composite key each container button opens.
vi.mock('@/providers/ContainerModalProvider', () => ({
  ContainerModalProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useContainerModal: () => ({ openModal }),
}))

function makeContainers(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: `container${i}`.padEnd(12, '0'),
    name: `app-${i}`,
  }))
}

describe('ContainerLinkList', () => {
  beforeEach(() => {
    openModal.mockClear()
  })

  it('renders every attached container, even beyond 3', () => {
    render(<ContainerLinkList containers={makeContainers(5)} hostId="host-1" />)

    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(5)
  })

  it('does not render a non-clickable "+N more" indicator', () => {
    render(<ContainerLinkList containers={makeContainers(7)} hostId="host-1" />)

    expect(screen.queryByText(/more/i)).toBeNull()
  })

  it('opens the container modal with the composite key (12-char id) on click', () => {
    const containers = [{ id: 'a'.repeat(64), name: 'web' }]
    render(<ContainerLinkList containers={containers} hostId="host-1" />)

    fireEvent.click(screen.getByRole('button', { name: 'web' }))

    expect(openModal).toHaveBeenCalledWith(`host-1:${'a'.repeat(12)}`)
  })

  it('renders a dash placeholder when there are no containers', () => {
    render(<ContainerLinkList containers={[]} hostId="host-1" />)

    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })
})
