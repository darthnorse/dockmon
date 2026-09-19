import { QueryCache, QueryClient } from '@tanstack/react-query'
import { ApiError } from '@/lib/api/client'

// Module-level so the cache persists across remounts (HMR, route changes, etc.)
export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    // Global session-expiry handling: a 401 on any data query means the session
    // is gone. Invalidate the current-user query (unless it's the one that
    // failed, to avoid a refetch loop) so ProtectedRoute redirects to /login.
    onError: (error, query) => {
      if (
        error instanceof ApiError &&
        error.status === 401 &&
        query.queryKey[0] !== 'auth'
      ) {
        void queryClient.invalidateQueries({ queryKey: ['auth', 'currentUser'] })
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})
