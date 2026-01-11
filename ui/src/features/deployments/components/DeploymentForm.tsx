/**
 * Deployment Form Component (v2.2.7+)
 *
 * Form for creating deployments from existing stacks.
 * - Select a stack from the Stacks API
 * - Select a target host
 * - Creates deployment with stack_name + host_id
 *
 * Note: Stack content is managed in StacksPage/StackForm.
 * This form only creates deployments that reference stacks.
 */

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useCreateDeployment } from '../hooks/useDeployments'
import { useStacks } from '../hooks/useStacks'
import type { Deployment } from '../types'

interface DeploymentFormProps {
  isOpen: boolean
  onClose: () => void
  hosts?: Array<{ id: string; name: string }>
  deployment?: Deployment  // If provided, form shows deployment info (read-only)
}

export function DeploymentForm({ isOpen, onClose, hosts = [], deployment }: DeploymentFormProps) {
  const navigate = useNavigate()
  const createDeployment = useCreateDeployment()
  const { data: stacks, isLoading: stacksLoading } = useStacks()

  const isEditMode = !!deployment

  // Form state
  const [stackName, setStackName] = useState('')
  const [hostId, setHostId] = useState('')

  // Validation errors
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Reset form when closed
  useEffect(() => {
    if (!isOpen) {
      setStackName('')
      setHostId('')
      setErrors({})
    }
  }, [isOpen])

  // Populate form when in edit mode
  useEffect(() => {
    if (isOpen && isEditMode && deployment) {
      setStackName(deployment.stack_name)
      setHostId(deployment.host_id)
    }
  }, [isOpen, isEditMode, deployment])

  // Set default host if only one available
  useEffect(() => {
    if (hosts && hosts.length === 1 && !hostId && hosts[0]) {
      setHostId(hosts[0].id)
    }
  }, [hosts, hostId])

  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {}

    if (!stackName) {
      newErrors.stackName = 'Please select a stack'
    }

    if (!hostId) {
      newErrors.hostId = 'Please select a host'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!validateForm()) {
      return
    }

    try {
      await createDeployment.mutateAsync({
        stack_name: stackName,
        host_id: hostId,
      })
      onClose()
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error'
      console.error('Failed to create deployment:', error)
      setErrors({ submit: errorMessage })
    }
  }

  const handleGoToStacks = () => {
    onClose()
    navigate('/stacks')
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-lg" data-testid="deployment-form">
        <DialogHeader>
          <DialogTitle>{isEditMode ? 'Deployment Details' : 'New Deployment'}</DialogTitle>
          <DialogDescription>
            {isEditMode
              ? 'View deployment configuration'
              : 'Deploy a stack to a Docker host'}
          </DialogDescription>
        </DialogHeader>

        {/* Edit mode: Show read-only info */}
        {isEditMode && deployment && (
          <div className="space-y-4">
            {/* Error Banner for failed deployments */}
            {(deployment.status === 'failed' || deployment.status === 'rolled_back') && deployment.error_message && (
              <div className="bg-destructive/10 border border-destructive rounded-lg p-4">
                <div className="flex gap-3">
                  <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <h4 className="font-semibold text-destructive">Deployment Failed</h4>
                    <p className="text-sm text-destructive/80 mt-1">{deployment.error_message}</p>
                  </div>
                </div>
              </div>
            )}

            <div className="space-y-3">
              <div>
                <Label className="text-muted-foreground">Stack</Label>
                <p className="font-mono">{deployment.stack_name}</p>
              </div>
              <div>
                <Label className="text-muted-foreground">Host</Label>
                <p>{deployment.host_name || deployment.host_id}</p>
              </div>
              <div>
                <Label className="text-muted-foreground">Status</Label>
                <p className="capitalize">{deployment.status}</p>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-4 border-t">
              <Button variant="outline" onClick={onClose}>
                Close
              </Button>
              <Button variant="outline" onClick={handleGoToStacks}>
                Edit Stack
              </Button>
            </div>
          </div>
        )}

        {/* Create mode: Show form */}
        {!isEditMode && (
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Stack Selection */}
            <div className="space-y-2">
              <Label htmlFor="stack">Stack *</Label>
              {stacksLoading ? (
                <p className="text-sm text-muted-foreground">Loading stacks...</p>
              ) : stacks && stacks.length > 0 ? (
                <Select value={stackName} onValueChange={setStackName}>
                  <SelectTrigger id="stack" className={errors.stackName ? 'border-destructive' : ''}>
                    <SelectValue placeholder="Select a stack" />
                  </SelectTrigger>
                  <SelectContent>
                    {stacks.map((stack) => (
                      <SelectItem key={stack.name} value={stack.name}>
                        {stack.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <div className="text-sm text-muted-foreground space-y-2">
                  <p>No stacks available. Create a stack first.</p>
                  <Button type="button" variant="outline" size="sm" onClick={handleGoToStacks}>
                    <Plus className="h-4 w-4 mr-1" />
                    Create Stack
                  </Button>
                </div>
              )}
              {errors.stackName && (
                <p className="text-sm text-destructive">{errors.stackName}</p>
              )}
            </div>

            {/* Host Selection */}
            <div className="space-y-2">
              <Label htmlFor="host">Target Host *</Label>
              <Select value={hostId} onValueChange={setHostId}>
                <SelectTrigger id="host" className={errors.hostId ? 'border-destructive' : ''}>
                  <SelectValue placeholder="Select a host" />
                </SelectTrigger>
                <SelectContent>
                  {[...hosts].sort((a, b) => a.name.localeCompare(b.name)).map((host) => (
                    <SelectItem key={host.id} value={host.id}>
                      {host.name || host.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.hostId && (
                <p className="text-sm text-destructive">{errors.hostId}</p>
              )}
            </div>

            {/* Submit Error */}
            {errors.submit && (
              <div className="bg-destructive/10 border border-destructive rounded-lg p-3">
                <p className="text-sm text-destructive">{errors.submit}</p>
              </div>
            )}

            {/* Form Actions */}
            <div className="flex items-center justify-end gap-3 pt-4 border-t">
              <Button
                type="button"
                variant="outline"
                onClick={onClose}
                disabled={createDeployment.isPending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={createDeployment.isPending || !stacks || stacks.length === 0}
                data-testid="create-deployment-submit"
              >
                {createDeployment.isPending ? 'Creating...' : 'Create Deployment'}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
