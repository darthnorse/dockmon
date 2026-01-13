/**
 * App Root Component
 *
 * ARCHITECTURE:
 * - QueryClientProvider for TanStack Query
 * - AuthProvider for authentication context
 * - WebSocketProvider for real-time updates
 * - Toaster for notifications
 * - Router for navigation with sidebar layout
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route, Navigate, useSearchParams } from 'react-router-dom'
import { Toaster } from 'sonner'
import { AuthProvider, useAuth } from '@/features/auth/AuthContext'
import { WebSocketProvider } from '@/lib/websocket/WebSocketProvider'
import { StatsProvider } from '@/lib/stats/StatsProvider'
import { ContainerModalProvider } from '@/providers'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { LoginPage } from '@/features/auth/LoginPage'
import { DashboardPage } from '@/features/dashboard/DashboardPage'
import { ContainersPage } from '@/features/containers/ContainersPage'
import { HostsPage } from '@/features/hosts/HostsPage'
import { EventsPage } from '@/features/events/EventsPage'
import { AlertsPage } from '@/features/alerts/AlertsPage'
import { AlertRulesPage } from '@/features/alerts/AlertRulesPage'
import { ContainerLogsPage } from '@/features/logs/ContainerLogsPage'
import { SettingsPage } from '@/features/settings/SettingsPage'
import { ChangePasswordModal } from '@/features/auth/ChangePasswordModal'
import { StacksPage } from '@/features/deployments/StacksPage'
import { QuickActionPage } from '@/features/quick-action/QuickActionPage'
import { AppLayout } from '@/components/layout/AppLayout'
import { LoadingSkeleton } from '@/components/layout/LoadingSkeleton'
import { useState, useEffect } from 'react'

// Create query client with sensible defaults
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

// Protected route wrapper
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return <LoadingSkeleton />
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

// Login route wrapper - redirects authenticated users to redirect URL or home
function LoginRoute() {
  const { isAuthenticated } = useAuth()
  const [searchParams] = useSearchParams()
  const redirectUrl = searchParams.get('redirect')

  if (isAuthenticated) {
    return <Navigate to={redirectUrl || '/'} replace />
  }

  return <LoginPage />
}

// App routes
function AppRoutes() {
  const { isFirstLogin } = useAuth()
  const [showPasswordDialog, setShowPasswordDialog] = useState(false)

  // Show password change dialog when first login is detected
  // This fires whenever isFirstLogin changes from false to true
  useEffect(() => {
    if (isFirstLogin) {
      setShowPasswordDialog(true)
    }
  }, [isFirstLogin])

  return (
    <>
      {/* First-run password change modal (cannot be dismissed) */}
      <ChangePasswordModal
        isOpen={showPasswordDialog}
        isRequired={isFirstLogin}
        onClose={() => setShowPasswordDialog(false)}
      />

      <Routes>
      {/* Public route - Login */}
      <Route path="/login" element={<LoginRoute />} />

      {/* Public route - Quick Action (notification links) */}
      <Route path="/quick-action" element={<QuickActionPage />} />

      {/* Protected routes - All use AppLayout with sidebar + WebSocket + Stats */}
      <Route
        element={
          <ProtectedRoute>
            <WebSocketProvider>
              <StatsProvider>
                <ContainerModalProvider>
                  <AppLayout />
                </ContainerModalProvider>
              </StatsProvider>
            </WebSocketProvider>
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/containers" element={<ContainersPage />} />
        <Route path="/stacks" element={<StacksPage />} />
        {/* Redirect old /deployments route to /stacks */}
        <Route path="/deployments" element={<Navigate to="/stacks" replace />} />
        <Route path="/hosts" element={<HostsPage />} />
        <Route path="/logs" element={<ContainerLogsPage />} />
        <Route path="/events" element={<EventsPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/alerts/rules" element={<AlertRulesPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      {/* Catch-all redirect */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </>
  )
}

// Main App component
export function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={import.meta.env.BASE_URL}>
          <AuthProvider>
            <AppRoutes />
            <Toaster
              position="bottom-right"
              expand={false}
              richColors
              closeButton
              theme="dark"
            />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
