/**
 * Orphaned Deployments Warning Banner
 *
 * Shows when deployments reference stacks that no longer exist on filesystem.
 * Provides link to repair modal.
 */

import { useState } from 'react'
import { AlertTriangle, X, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useOrphanedDeployments } from '../hooks/useDeployments'
import { OrphanedDeploymentsModal } from './OrphanedDeploymentsModal'

export function OrphanedDeploymentsBanner() {
  const { data, isLoading } = useOrphanedDeployments()
  const [isDismissed, setIsDismissed] = useState(false)
  const [showModal, setShowModal] = useState(false)

  // Don't show if loading, no orphans, or dismissed
  if (isLoading || !data || data.count === 0 || isDismissed) {
    return null
  }

  const count = data.count
  const pluralized = count === 1 ? 'deployment references a' : 'deployments reference'

  return (
    <>
      <div className="mb-4 rounded-lg bg-amber-500/10 border border-amber-500/30 p-3">
        <div className="flex items-center gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-500 flex-shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-medium text-amber-700 dark:text-amber-400">
              {count} {pluralized} missing stack{count === 1 ? '' : 's'}
            </p>
            <p className="text-xs text-amber-600 dark:text-amber-500 mt-0.5">
              These deployments reference stacks that no longer exist on the filesystem
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowModal(true)}
              className="gap-2 border-amber-500/50 text-amber-700 hover:bg-amber-500/10 dark:text-amber-400"
            >
              <Wrench className="h-4 w-4" />
              Repair
            </Button>
            <button
              onClick={() => setIsDismissed(true)}
              className="p-1 rounded hover:bg-amber-500/20 transition-colors"
              aria-label="Dismiss"
            >
              <X className="h-4 w-4 text-amber-600 dark:text-amber-500" />
            </button>
          </div>
        </div>
      </div>

      <OrphanedDeploymentsModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        orphanedDeployments={data.deployments}
      />
    </>
  )
}
