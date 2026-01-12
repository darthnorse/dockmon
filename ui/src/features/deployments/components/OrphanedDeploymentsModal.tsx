/**
 * Orphaned Deployments Repair Modal
 *
 * Shows list of orphaned deployments with repair options:
 * - Reassign to existing stack
 * - Delete deployment record
 * - Recreate stack from running containers
 */

import { useState } from 'react'
import { AlertTriangle, Trash2, RefreshCw, ArrowRight, Eye, Loader2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Textarea } from '@/components/ui/textarea'
import { useStacks } from '../hooks/useStacks'
import { useRepairDeployment, useComposePreview } from '../hooks/useDeployments'
import type { OrphanedDeployment, RepairAction } from '../types'

interface Props {
  isOpen: boolean
  onClose: () => void
  orphanedDeployments: OrphanedDeployment[]
}

export function OrphanedDeploymentsModal({ isOpen, onClose, orphanedDeployments }: Props) {
  const { data: stacks } = useStacks()
  const repairDeployment = useRepairDeployment()

  const [selectedDeployment, setSelectedDeployment] = useState<OrphanedDeployment | null>(null)
  const [selectedAction, setSelectedAction] = useState<RepairAction | null>(null)
  const [selectedStack, setSelectedStack] = useState<string>('')
  const [showPreview, setShowPreview] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  // Preview compose for recreate action
  const { data: composePreview, isLoading: isLoadingPreview } = useComposePreview(
    selectedAction === 'recreate' && showPreview ? selectedDeployment?.id ?? null : null
  )

  const handleRepair = async () => {
    if (!selectedDeployment || !selectedAction) return

    if (selectedAction === 'delete') {
      setShowDeleteConfirm(true)
      return
    }

    if (selectedAction === 'reassign' && !selectedStack) {
      return
    }

    const mutationParams: { deploymentId: string; action: RepairAction; newStackName?: string } = {
      deploymentId: selectedDeployment.id,
      action: selectedAction,
    }
    if (selectedAction === 'reassign') {
      mutationParams.newStackName = selectedStack
    }
    await repairDeployment.mutateAsync(mutationParams)

    // Reset state after successful repair
    resetSelection()
  }

  const confirmDelete = async () => {
    if (!selectedDeployment) return

    await repairDeployment.mutateAsync({
      deploymentId: selectedDeployment.id,
      action: 'delete',
    })

    setShowDeleteConfirm(false)
    resetSelection()
  }

  const resetSelection = () => {
    setSelectedDeployment(null)
    setSelectedAction(null)
    setSelectedStack('')
    setShowPreview(false)
  }

  const handleClose = () => {
    resetSelection()
    onClose()
  }

  // Check if all deployments have been repaired
  const remainingOrphans = orphanedDeployments.filter(
    (d) => !repairDeployment.variables?.deploymentId || d.id !== repairDeployment.variables.deploymentId
  )

  if (remainingOrphans.length === 0 && isOpen) {
    // All fixed, close modal
    handleClose()
    return null
  }

  return (
    <>
      <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              Orphaned Deployments
            </DialogTitle>
            <DialogDescription>
              These deployments reference stacks that no longer exist. Choose a repair action for each.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 mt-4">
            {orphanedDeployments.map((deployment) => (
              <div
                key={deployment.id}
                className={`p-4 rounded-lg border ${
                  selectedDeployment?.id === deployment.id
                    ? 'border-primary bg-primary/5'
                    : 'border-border'
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium font-mono truncate">{deployment.stack_name}</p>
                    <p className="text-sm text-muted-foreground">
                      Host: {deployment.host_name || deployment.host_id.slice(0, 8)}
                    </p>
                    {deployment.container_ids && deployment.container_ids.length > 0 && (
                      <p className="text-xs text-muted-foreground mt-1">
                        {deployment.container_ids.length} container(s) linked
                      </p>
                    )}
                  </div>

                  {selectedDeployment?.id !== deployment.id ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setSelectedDeployment(deployment)
                        setSelectedAction(null)
                        setSelectedStack('')
                        setShowPreview(false)
                      }}
                    >
                      Select
                    </Button>
                  ) : (
                    <div className="flex flex-col gap-2 shrink-0">
                      {/* Action Selection */}
                      <Select
                        value={selectedAction || ''}
                        onValueChange={(value) => {
                          setSelectedAction(value as RepairAction)
                          setShowPreview(false)
                        }}
                      >
                        <SelectTrigger className="w-[180px]">
                          <SelectValue placeholder="Choose action..." />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="reassign">
                            <span className="flex items-center gap-2">
                              <ArrowRight className="h-4 w-4" />
                              Reassign to stack
                            </span>
                          </SelectItem>
                          <SelectItem value="delete">
                            <span className="flex items-center gap-2">
                              <Trash2 className="h-4 w-4" />
                              Delete record
                            </span>
                          </SelectItem>
                          {deployment.container_ids && deployment.container_ids.length > 0 && (
                            <SelectItem value="recreate">
                              <span className="flex items-center gap-2">
                                <RefreshCw className="h-4 w-4" />
                                Recreate from containers
                              </span>
                            </SelectItem>
                          )}
                        </SelectContent>
                      </Select>

                      {/* Stack Selection for Reassign */}
                      {selectedAction === 'reassign' && (
                        <Select value={selectedStack} onValueChange={setSelectedStack}>
                          <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="Select stack..." />
                          </SelectTrigger>
                          <SelectContent>
                            {stacks?.map((stack) => (
                              <SelectItem key={stack.name} value={stack.name}>
                                {stack.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}

                      {/* Preview Button for Recreate */}
                      {selectedAction === 'recreate' && !showPreview && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setShowPreview(true)}
                          className="gap-2"
                        >
                          <Eye className="h-4 w-4" />
                          Preview
                        </Button>
                      )}

                      {/* Apply Button */}
                      <Button
                        size="sm"
                        onClick={handleRepair}
                        disabled={
                          repairDeployment.isPending ||
                          !selectedAction ||
                          (selectedAction === 'reassign' && !selectedStack)
                        }
                      >
                        {repairDeployment.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          'Apply'
                        )}
                      </Button>

                      {/* Cancel Selection */}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={resetSelection}
                      >
                        Cancel
                      </Button>
                    </div>
                  )}
                </div>

                {/* Compose Preview */}
                {selectedDeployment?.id === deployment.id &&
                  selectedAction === 'recreate' &&
                  showPreview && (
                    <div className="mt-4 border-t pt-4">
                      {isLoadingPreview ? (
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Generating compose preview...
                        </div>
                      ) : composePreview ? (
                        <div className="space-y-2">
                          <p className="text-sm font-medium">Generated compose.yaml:</p>
                          {composePreview.warnings.length > 0 && (
                            <div className="text-xs text-amber-600 dark:text-amber-500 space-y-1">
                              {composePreview.warnings.map((warning, i) => (
                                <p key={i}>Note: {warning}</p>
                              ))}
                            </div>
                          )}
                          <Textarea
                            value={composePreview.compose_yaml}
                            readOnly
                            className="font-mono text-xs h-[200px] resize-none"
                          />
                          <p className="text-xs text-muted-foreground">
                            Services: {composePreview.services.join(', ') || 'None'}
                          </p>
                        </div>
                      ) : null}
                    </div>
                  )}
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Deployment Record</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete the deployment record for "{selectedDeployment?.stack_name}"?
              This only removes the deployment record from DockMon - any running containers will not be affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
