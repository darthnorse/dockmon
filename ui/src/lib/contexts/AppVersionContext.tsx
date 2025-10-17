/**
 * App Version Context
 *
 * Provides application version from database to all components.
 * Version is set by AppLayout (which already fetches it via /upgrade-notice).
 * No duplicate API calls - uses existing data.
 */

import { createContext, useContext, ReactNode } from 'react'

interface AppVersionContextType {
  version: string
}

const AppVersionContext = createContext<AppVersionContextType | undefined>(undefined)

interface AppVersionProviderProps {
  version: string
  children: ReactNode
}

export function AppVersionProvider({ version, children }: AppVersionProviderProps) {
  return (
    <AppVersionContext.Provider value={{ version }}>
      {children}
    </AppVersionContext.Provider>
  )
}

export function useAppVersion() {
  const context = useContext(AppVersionContext)
  if (context === undefined) {
    throw new Error('useAppVersion must be used within AppVersionProvider')
  }
  return context
}
