/**
 * Regression (discussion #236): a malformed compose (HTTP 400) surfaced from the
 * pre-deploy port check was rendered as "unable to reach host", masking the real
 * problem. The banner now distinguishes a 400 (compose invalid) from a
 * connectivity failure.
 */
import { describe, it, expect } from 'vitest'

import { render, screen } from '@/test/utils'
import { ApiError } from '@/lib/api/client'

import { PortConflictBanner } from './PortConflictBanner'

describe('PortConflictBanner', () => {
  it('shows a blocking compose-invalid message for a 400', () => {
    const err = new ApiError(
      'Compose file has a tab character at line 2, column 1.',
      400,
    )
    render(
      <PortConflictBanner conflicts={[]} isLoading={false} error={err} hostName="prod-host" />,
    )

    expect(screen.getByText('Compose file is invalid')).toBeInTheDocument()
    expect(screen.getByText(/tab character at line 2/)).toBeInTheDocument()
    // Must NOT masquerade as a connectivity problem.
    expect(screen.queryByText(/unable to reach/i)).not.toBeInTheDocument()
  })

  it('shows the neutral "check skipped" message for a non-400 error', () => {
    const err = new ApiError('Host not available for port check', 409)
    render(
      <PortConflictBanner conflicts={[]} isLoading={false} error={err} hostName="prod-host" />,
    )

    expect(screen.getByText(/unable to reach/i)).toBeInTheDocument()
    expect(screen.getByText(/prod-host/)).toBeInTheDocument()
    expect(screen.queryByText('Compose file is invalid')).not.toBeInTheDocument()
  })

  it('renders nothing when there are no conflicts and no error', () => {
    const { container } = render(
      <PortConflictBanner conflicts={[]} isLoading={false} error={null} hostName="prod-host" />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('lists conflicts when present', () => {
    render(
      <PortConflictBanner
        conflicts={[{ port: 8080, protocol: 'tcp', container_id: 'abc123def456', container_name: 'nginx' }]}
        isLoading={false}
        error={null}
        hostName="prod-host"
      />,
    )
    expect(screen.getByText(/Port conflicts on prod-host/)).toBeInTheDocument()
    expect(screen.getByText('nginx')).toBeInTheDocument()
  })
})
