/**
 * Unit tests for HostContainersTab.
 *
 * The tab owns the scroll container that VirtualizedTable wires its
 * element-scroll virtualizer to. If this contract breaks (e.g. a future
 * refactor stops forwarding the captured element to ContainerTable),
 * scrolling a long container list inside the host modal silently fails.
 */

import { describe, it, expect, vi } from 'vitest'
import { render } from '@/test/utils'

import { HostContainersTab } from './HostContainersTab'

const containerTableSpy = vi.fn()

vi.mock('@/features/containers/ContainerTable', () => ({
  ContainerTable: (props: { hostId?: string; scrollElement?: HTMLElement | null }) => {
    containerTableSpy(props)
    return <div data-testid="container-table-stub" />
  },
}))

describe('HostContainersTab', () => {
  it('forwards the scroll-container element (with overflow-y-auto) to ContainerTable', () => {
    containerTableSpy.mockClear()
    const { getByTestId } = render(<HostContainersTab hostId="test-host" />)

    // Callback ref attaches synchronously after the first render, which
    // triggers a second render with the element. We assert on the final
    // call: ContainerTable receives the actual scroll container.
    const scrollDiv = getByTestId('host-containers-scroll')
    const props = containerTableSpy.mock.lastCall?.[0] as { hostId?: string; scrollElement?: HTMLElement | null }
    expect(props.hostId).toBe('test-host')
    expect(props.scrollElement).toBe(scrollDiv)
    expect(scrollDiv.className).toContain('overflow-y-auto')
  })
})
