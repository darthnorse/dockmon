/**
 * ContainerModalProvider - Global state management for container modal
 *
 * Provides a single modal instance accessible from anywhere in the app via useContainerModal() hook.
 * Eliminates code duplication and provides better UX by avoiding navigation/page changes.
 *
 * Usage:
 *   const { openModal } = useContainerModal()
 *   openModal(compositeKey, 'logs')  // Opens modal on logs tab
 */

import { createContext, useContext, useState, ReactNode, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ContainerDetailsModal } from '@/features/containers/components/ContainerDetailsModal'
import { parseCompositeKey } from '@/lib/utils/containerKeys'
import type { Container } from '@/features/containers/types'
import { useStatsContext } from '@/lib/stats/StatsProvider'

interface ContainerModalState {
  isOpen: boolean
  containerId: string | null // Composite key: {host_id}:{container_id}
  initialTab: string // 'info' | 'logs' | 'events' | 'alerts' | 'updates' | 'health'
}

interface ContainerModalContextValue {
  // Open modal with optional initial tab (defaults to 'info')
  openModal: (compositeKey: string, initialTab?: string) => void

  // Close modal
  closeModal: () => void

  // Check if modal is open (useful for debugging)
  isModalOpen: boolean
}

const ContainerModalContext = createContext<ContainerModalContextValue | null>(null)

export function ContainerModalProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const { containerStats } = useStatsContext()
  const [state, setState] = useState<ContainerModalState>({
    isOpen: false,
    containerId: null,
    initialTab: 'info',
  })

  // Get container from cached query data OR StatsProvider (no additional API call)
  // NOTE: Dual data source pattern required because:
  //   - Container list page: Uses React Query cache (HTTP API)
  //   - Dashboard: Uses StatsProvider (WebSocket data)
  // TODO: Future refactor - make modal self-fetching to decouple from data sources
  const container = useMemo(() => {
    if (!state.containerId) return null

    // Parse composite key
    const { hostId, containerId } = parseCompositeKey(state.containerId)

    // Try React Query cache first (used by container list page)
    const containers = queryClient.getQueryData<Container[]>(['containers'])
    if (containers) {
      const found = containers.find((c) => c.host_id === hostId && c.id === containerId)
      if (found) return found
    }

    // Fallback to StatsProvider (used by dashboard)
    const statsContainer = containerStats.get(state.containerId)
    if (statsContainer) {
      // StatsProvider container type matches Container type from WebSocket
      return statsContainer as Container
    }

    return null
  }, [state.containerId, queryClient, containerStats])

  const openModal = (compositeKey: string, initialTab: string = 'info') => {
    setState({
      isOpen: true,
      containerId: compositeKey,
      initialTab,
    })
  }

  const closeModal = () => {
    setState({
      isOpen: false,
      containerId: null,
      initialTab: 'info',
    })
  }

  const contextValue: ContainerModalContextValue = {
    openModal,
    closeModal,
    isModalOpen: state.isOpen,
  }

  return (
    <ContainerModalContext.Provider value={contextValue}>
      {children}

      {/* Global modal instance - single instance for entire app */}
      {/* Uses cached container data from React Query - no additional API calls */}
      <ContainerDetailsModal
        containerId={state.containerId}
        container={container}
        open={state.isOpen}
        onClose={closeModal}
        initialTab={state.initialTab}
      />
    </ContainerModalContext.Provider>
  )
}

/**
 * Hook to access container modal
 * @throws Error if used outside ContainerModalProvider
 */
export function useContainerModal() {
  const context = useContext(ContainerModalContext)
  if (!context) {
    throw new Error('useContainerModal must be used within ContainerModalProvider')
  }
  return context
}
