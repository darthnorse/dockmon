/**
 * ContainerModalProvider - Global state management for container modal
 *
 * Provides a single modal instance accessible from anywhere in the app via useContainerModal() hook.
 * Eliminates code duplication and provides better UX by avoiding navigation/page changes.
 *
 * Architecture:
 * - Provider: Pure state management (open/closed, containerId, initialTab)
 * - Modal: Self-fetching data based on containerId (decoupled from provider)
 *
 * Usage:
 *   const { openModal } = useContainerModal()
 *   openModal(compositeKey, 'logs')  // Opens modal on logs tab
 */

import { createContext, useContext, useState, ReactNode } from 'react'
import { ContainerDetailsModal } from '@/features/containers/components/ContainerDetailsModal'

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

  // Update container ID (used when container is recreated during updates)
  updateContainerId: (newCompositeKey: string) => void

  // Check if modal is open (useful for debugging)
  isModalOpen: boolean
}

const ContainerModalContext = createContext<ContainerModalContextValue | null>(null)

export function ContainerModalProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ContainerModalState>({
    isOpen: false,
    containerId: null,
    initialTab: 'info',
  })

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

  const updateContainerId = (newCompositeKey: string) => {
    setState((prev) => ({
      ...prev,
      containerId: newCompositeKey,
    }))
  }

  const contextValue: ContainerModalContextValue = {
    openModal,
    closeModal,
    updateContainerId,
    isModalOpen: state.isOpen,
  }

  return (
    <ContainerModalContext.Provider value={contextValue}>
      {children}

      {/* Global modal instance - single instance for entire app */}
      {/* Modal fetches its own data - provider just manages state */}
      <ContainerDetailsModal
        containerId={state.containerId}
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
