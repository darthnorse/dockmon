/**
 * Test Utilities
 * Helper functions for testing React components
 */

import { ReactElement, ReactNode } from 'react'
import { render, RenderOptions } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'

import { AuthContext, type AuthContextValue } from '@/features/auth/AuthContext'
import {
  WebSocketContext,
  type WebSocketContextValue,
} from '@/lib/websocket/WebSocketProvider'
import { StatsContext, type StatsContextValue } from '@/lib/stats/StatsProvider'
import { ContainerModalProvider } from '@/providers/ContainerModalProvider'

// A permissive default so component tests that don't explicitly set up auth
// still render. Tests that exercise auth-gated logic should pass overrides.
const defaultAuthContext: AuthContextValue = {
  user: { id: 1, username: 'test-user', groups: [{ id: 1, name: 'Administrators' }] },
  capabilities: ['*'],
  isLoading: false,
  isAuthenticated: true,
  isFirstLogin: false,
  mustChangePassword: false,
  isAdmin: true,
  hasCapability: () => true,
  login: async () => {},
  logout: async () => {},
}

export function MockAuthProvider({
  children,
  value,
}: {
  children: ReactNode
  value?: Partial<AuthContextValue>
}) {
  const merged: AuthContextValue = { ...defaultAuthContext, ...value }
  return <AuthContext.Provider value={merged}>{children}</AuthContext.Provider>
}

// Stub out the websocket connection in tests; consumers see "disconnected"
// status and noop send/addMessageHandler.
const noopWebSocket: WebSocketContextValue = {
  status: 'disconnected',
  send: () => {},
  addMessageHandler: () => () => {},
}

export function MockWebSocketProvider({ children }: { children: ReactNode }) {
  return <WebSocketContext.Provider value={noopWebSocket}>{children}</WebSocketContext.Provider>
}

const emptyStats: StatsContextValue = {
  hostMetrics: new Map(),
  hostSparklines: new Map(),
  containerStats: new Map(),
  containerSparklines: new Map(),
  lastUpdate: null,
  isConnected: false,
}

export function MockStatsProvider({ children }: { children: ReactNode }) {
  return <StatsContext.Provider value={emptyStats}>{children}</StatsContext.Provider>
}

/**
 * Create a new QueryClient for each test
 * Prevents test pollution
 */
export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

interface AllTheProvidersProps {
  children: React.ReactNode
}

/**
 * Wrapper with all necessary providers for testing
 */
export function AllTheProviders({ children }: AllTheProvidersProps) {
  const queryClient = createTestQueryClient()

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <MockAuthProvider>
          <MockWebSocketProvider>
            <MockStatsProvider>
              <ContainerModalProvider>{children}</ContainerModalProvider>
            </MockStatsProvider>
          </MockWebSocketProvider>
        </MockAuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

/**
 * Custom render function that includes all providers
 */
export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) {
  return render(ui, { wrapper: AllTheProviders, ...options })
}

// Re-export everything from RTL
export * from '@testing-library/react'
export { renderWithProviders as render }
