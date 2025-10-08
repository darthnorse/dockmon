/**
 * AppLayout Tests
 * Tests layout structure with sidebar and outlet
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AppLayout } from './AppLayout'

// Mock Sidebar
vi.mock('./Sidebar', () => ({
  Sidebar: () => <aside data-testid="sidebar">Sidebar Mock</aside>,
}))

// Mock WebSocket Provider
vi.mock('@/lib/websocket/WebSocketProvider', () => ({
  useWebSocketContext: () => ({
    status: 'connected',
    send: vi.fn(),
  }),
}))

function renderWithRouter() {
  return render(
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppLayout />}>
          <Route index element={<div>Page Content</div>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

describe('AppLayout', () => {
  describe('rendering', () => {
    it('should render sidebar', () => {
      renderWithRouter()

      expect(screen.getByTestId('sidebar')).toBeInTheDocument()
    })

    it('should render outlet content', () => {
      renderWithRouter()

      expect(screen.getByText('Page Content')).toBeInTheDocument()
    })

    it('should have main content area', () => {
      const { container } = renderWithRouter()

      const main = container.querySelector('main')
      expect(main).toBeInTheDocument()
    })

    it('should have minimum height', () => {
      const { container } = renderWithRouter()

      const main = container.querySelector('main')
      expect(main).toHaveClass('min-h-screen')
    })

    it('should have transition for sidebar', () => {
      const { container } = renderWithRouter()

      const main = container.querySelector('main')
      expect(main).toHaveClass('transition-all')
    })
  })

  describe('layout structure', () => {
    it('should have root background', () => {
      const { container } = renderWithRouter()

      const root = container.querySelector('.bg-background')
      expect(root).toBeInTheDocument()
    })

    it('should apply left padding for sidebar', () => {
      const { container } = renderWithRouter()

      const main = container.querySelector('main')
      // Should have padding-left class for sidebar
      expect(main?.className).toMatch(/pl-/)
    })
  })
})
