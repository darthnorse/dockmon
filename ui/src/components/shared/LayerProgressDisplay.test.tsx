import { describe, it, expect, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { LayerProgressDisplay } from './LayerProgressDisplay'
import { WebSocketContext } from '@/lib/websocket/WebSocketProvider'
import type { WebSocketMessage } from '@/lib/websocket/useWebSocket'

function renderWithSocket(props: { hostId: string; containerId: string }) {
  let handler: ((message: WebSocketMessage) => void) | null = null
  const addMessageHandler = (h: (message: WebSocketMessage) => void) => {
    handler = h
    return () => { handler = null }
  }
  render(
    <WebSocketContext.Provider value={{ status: 'connected', send: vi.fn(), addMessageHandler }}>
      <LayerProgressDisplay {...props} initialMessage="Initializing update..." />
    </WebSocketContext.Provider>
  )
  return (message: WebSocketMessage) => act(() => handler?.(message))
}

describe('LayerProgressDisplay', () => {
  it('applies container_update_progress keyed by container_id, as the backend emits it', () => {
    const send = renderWithSocket({ hostId: 'h1', containerId: 'aaa111111111' })

    send({
      type: 'container_update_progress',
      data: { host_id: 'h1', container_id: 'aaa111111111', stage: 'backup', progress: 40, message: 'Creating backup' },
    })

    expect(screen.getByText('Creating backup')).toBeInTheDocument()
    expect(screen.queryByText('backup')).not.toBeInTheDocument()
    expect(screen.getByText('40%')).toBeInTheDocument()
  })

  it('ignores progress for another container on the same host', () => {
    const send = renderWithSocket({ hostId: 'h1', containerId: 'aaa111111111' })

    send({
      type: 'container_update_progress',
      data: { host_id: 'h1', container_id: 'bbb222222222', stage: 'backup', progress: 40, message: 'Creating backup' },
    })

    expect(screen.getByText('Initializing update...')).toBeInTheDocument()
    expect(screen.queryByText('40%')).not.toBeInTheDocument()
  })

  it('hands the header back to the stage message once the pull is done', () => {
    const send = renderWithSocket({ hostId: 'h1', containerId: 'aaa111111111' })

    send({
      type: 'container_update_layer_progress',
      data: {
        host_id: 'h1', entity_id: 'aaa111111111', overall_progress: 100, total_layers: 1, remaining_layers: 0,
        summary: '1/1 layers complete', layers: [{ id: 'abc', status: 'Pull complete', current: 10, total: 10, percent: 100 }],
      },
    })
    expect(screen.getByText('1/1 layers complete')).toBeInTheDocument()

    send({
      type: 'container_update_progress',
      data: { host_id: 'h1', container_id: 'aaa111111111', stage: 'backup', progress: 60, message: 'Creating backup' },
    })

    expect(screen.getByText('Creating backup')).toBeInTheDocument()
    expect(screen.queryByText('1/1 layers complete')).not.toBeInTheDocument()
    expect(screen.getByText('60%')).toBeInTheDocument()
    expect(screen.getByText('Pull complete')).toBeInTheDocument()
  })

  it('renders an agent stage that carries no percentage', () => {
    const send = renderWithSocket({ hostId: 'h1', containerId: 'aaa111111111' })

    send({
      type: 'container_update_progress',
      data: { host_id: 'h1', container_id: 'aaa111111111', stage: 'health', message: 'Waiting for health check' },
    })

    expect(screen.getByText('Waiting for health check')).toBeInTheDocument()
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument()
  })
})
