/**
 * Deployment Form Component (v2.2.7+)
 *
 * Two-column modal for creating deployments:
 * - Left: Searchable stack list
 * - Right: Editable compose.yaml + .env preview
 *
 * Features:
 * - Search/filter stacks
 * - Preview stack content before deploying
 * - Inline editing with confirmation to save changes
 * - Select target host
 */

import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Search, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
import { cn } from '@/lib/utils'
import { useCreateDeployment } from '../hooks/useDeployments'
import { useStacks, useStack, useUpdateStack } from '../hooks/useStacks'
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
  const updateStack = useUpdateStack()
  const { data: stacks, isLoading: stacksLoading } = useStacks()

  const isEditMode = !!deployment

  // Form state for create mode
  const [selectedStackName, setSelectedStackName] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [composeYaml, setComposeYaml] = useState('')
  const [envContent, setEnvContent] = useState('')
  const [hostId, setHostId] = useState('')

  // Track original content for change detection
  const [originalCompose, setOriginalCompose] = useState('')
  const [originalEnv, setOriginalEnv] = useState('')

  // UI state
  const [showConfirmDialog, setShowConfirmDialog] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Fetch full stack content when selected
  const { data: selectedStack, isLoading: stackLoading } = useStack(selectedStackName)

  // Derived state
  const hasChanges = composeYaml !== originalCompose || envContent !== originalEnv
  const isSubmitting = createDeployment.isPending || updateStack.isPending

  // Filter stacks by search query
  const filteredStacks = stacks?.filter(s =>
    s.name.toLowerCase().includes(searchQuery.toLowerCase())
  ) || []

  // Memoize sorted hosts to prevent re-sorting on every render
  const sortedHosts = useMemo(
    () => [...hosts].sort((a, b) => a.name.localeCompare(b.name)),
    [hosts]
  )

  // Helper to reset all form state
  const resetForm = () => {
    setSelectedStackName(null)
    setSearchQuery('')
    setComposeYaml('')
    setEnvContent('')
    setOriginalCompose('')
    setOriginalEnv('')
    setHostId('')
    setErrors({})
    setShowConfirmDialog(false)
  }

  // Reset form when modal closes
  useEffect(() => {
    if (!isOpen) {
      resetForm()
    }
  }, [isOpen])

  // Populate form when editing existing deployment
  useEffect(() => {
    if (isOpen && isEditMode && deployment) {
      setSelectedStackName(deployment.stack_name)
      setHostId(deployment.host_id)
    }
  }, [isOpen, isEditMode, deployment])

  // Load stack content when selected
  useEffect(() => {
    if (selectedStack) {
      const compose = selectedStack.compose_yaml || ''
      const env = selectedStack.env_content || ''
      setComposeYaml(compose)
      setEnvContent(env)
      setOriginalCompose(compose)
      setOriginalEnv(env)
    }
  }, [selectedStack])

  // Set default host if only one available
  useEffect(() => {
    if (hosts && hosts.length === 1 && !hostId && hosts[0]) {
      setHostId(hosts[0].id)
    }
  }, [hosts, hostId])

  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {}

    if (!selectedStackName) {
      newErrors.stack = 'Please select a stack'
    }

    if (!composeYaml.trim()) {
      newErrors.compose = 'Compose YAML cannot be empty'
    }

    if (!hostId) {
      newErrors.host = 'Please select a host'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleCreate = async () => {
    if (!validateForm()) return

    if (hasChanges) {
      setShowConfirmDialog(true)
      return
    }

    await doCreateDeployment()
  }

  const doCreateDeployment = async () => {
    setShowConfirmDialog(false)

    try {
      // Save stack changes first if any
      if (hasChanges && selectedStackName) {
        await updateStack.mutateAsync({
          name: selectedStackName,
          compose_yaml: composeYaml,
          env_content: envContent || null,
        })
      }

      // Create deployment (selectedStackName guaranteed by validateForm, but be defensive)
      if (!selectedStackName) {
        setErrors({ submit: 'No stack selected' })
        return
      }
      await createDeployment.mutateAsync({
        stack_name: selectedStackName,
        host_id: hostId,
      })

      onClose()
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error'
      console.error('Failed to create deployment:', error)
      setErrors({ submit: errorMessage })
    }
  }

  const handleStackSelect = (stackName: string) => {
    // Reset content when switching stacks
    if (stackName !== selectedStackName) {
      setComposeYaml('')
      setEnvContent('')
      setOriginalCompose('')
      setOriginalEnv('')
    }
    setSelectedStackName(stackName)
    setErrors({})
  }

  const handleGoToStacks = () => {
    onClose()
    navigate('/stacks')
  }

  // Render stack list content with clear state handling
  const renderStackList = () => {
    if (stacksLoading) {
      return <p className="text-sm text-muted-foreground p-2">Loading stacks...</p>
    }

    if (filteredStacks.length > 0) {
      return filteredStacks.map((stack) => (
        <button
          key={stack.name}
          type="button"
          onClick={() => handleStackSelect(stack.name)}
          className={cn(
            'w-full text-left px-3 py-2 rounded-md transition-colors flex items-center justify-between',
            selectedStackName === stack.name
              ? 'bg-primary text-primary-foreground'
              : 'hover:bg-muted'
          )}
        >
          <span className="truncate">{stack.name}</span>
          {stack.deployment_count > 0 && (
            <Badge
              variant={selectedStackName === stack.name ? 'secondary' : 'outline'}
              className="ml-2 shrink-0"
            >
              {stack.deployment_count}
            </Badge>
          )}
        </button>
      ))
    }

    if (stacks && stacks.length === 0) {
      return (
        <div className="text-sm text-muted-foreground p-2 space-y-3">
          <p>No stacks available.</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleGoToStacks}
          >
            <Plus className="h-4 w-4 mr-1" />
            Create Stack
          </Button>
        </div>
      )
    }

    return (
      <p className="text-sm text-muted-foreground p-2">
        No stacks match "{searchQuery}"
      </p>
    )
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent
        className={isEditMode ? 'max-w-lg' : 'max-w-5xl max-h-[85vh]'}
        data-testid="deployment-form"
      >
        <DialogHeader>
          <DialogTitle>{isEditMode ? 'Deployment Details' : 'New Deployment'}</DialogTitle>
          <DialogDescription>
            {isEditMode
              ? 'View deployment configuration'
              : 'Select a stack and target host to deploy'}
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

        {/* Create mode: Two-column layout */}
        {!isEditMode && (
          <>
            <div className="grid grid-cols-[280px_1fr] gap-6 min-h-[500px]">
              {/* LEFT COLUMN: Stack list with search */}
              <div className="flex flex-col border-r pr-4">
                {/* Search input */}
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Search stacks..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9"
                  />
                </div>

                {/* Stack list */}
                <div className="flex-1 overflow-y-auto space-y-1">
                  {renderStackList()}
                </div>

                {errors.stack && (
                  <p className="text-sm text-destructive mt-2">{errors.stack}</p>
                )}
              </div>

              {/* RIGHT COLUMN: Stack preview/edit */}
              <div className="flex flex-col overflow-hidden">
                {selectedStackName ? (
                  stackLoading ? (
                    <div className="flex items-center justify-center h-full text-muted-foreground">
                      Loading stack content...
                    </div>
                  ) : (
                    <>
                      {/* Stack name header */}
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="font-semibold text-lg">{selectedStackName}</h3>
                        {hasChanges && (
                          <Badge variant="secondary">Modified</Badge>
                        )}
                      </div>

                      {/* Editable content */}
                      <div className="flex-1 overflow-y-auto space-y-4 pr-2">
                        <div>
                          <Label htmlFor="compose-yaml">Compose YAML</Label>
                          <Textarea
                            id="compose-yaml"
                            value={composeYaml}
                            onChange={(e) => setComposeYaml(e.target.value)}
                            disabled={showConfirmDialog}
                            className={cn(
                              "font-mono text-sm h-64 resize-none mt-1.5",
                              errors.compose && "border-destructive"
                            )}
                            placeholder="Loading..."
                          />
                          {errors.compose && (
                            <p className="text-sm text-destructive mt-1">{errors.compose}</p>
                          )}
                        </div>

                        <div>
                          <Label htmlFor="env-content">Environment Variables (.env)</Label>
                          <Textarea
                            id="env-content"
                            value={envContent}
                            onChange={(e) => setEnvContent(e.target.value)}
                            disabled={showConfirmDialog}
                            className="font-mono text-sm h-28 resize-none mt-1.5"
                            placeholder="Optional - KEY=value format"
                          />
                        </div>
                      </div>

                      {/* Host selection */}
                      <div className="pt-4 border-t mt-4">
                        <Label htmlFor="host">Target Host *</Label>
                        <Select value={hostId} onValueChange={setHostId} disabled={showConfirmDialog}>
                          <SelectTrigger
                            id="host"
                            className={cn('mt-1.5', errors.host && 'border-destructive')}
                          >
                            <SelectValue placeholder="Select a host" />
                          </SelectTrigger>
                          <SelectContent>
                            {sortedHosts.length === 0 ? (
                              <div className="py-2 px-3 text-sm text-muted-foreground">
                                No hosts available
                              </div>
                            ) : (
                              sortedHosts.map((host) => (
                                <SelectItem key={host.id} value={host.id}>
                                  {host.name || host.id}
                                </SelectItem>
                              ))
                            )}
                          </SelectContent>
                        </Select>
                        {errors.host && (
                          <p className="text-sm text-destructive mt-1">{errors.host}</p>
                        )}
                      </div>
                    </>
                  )
                ) : (
                  <div className="flex items-center justify-center h-full text-muted-foreground">
                    Select a stack from the list
                  </div>
                )}
              </div>
            </div>

            {/* Submit Error */}
            {errors.submit && (
              <div className="bg-destructive/10 border border-destructive rounded-lg p-3 mt-4">
                <p className="text-sm text-destructive">{errors.submit}</p>
              </div>
            )}

            {/* Footer */}
            <DialogFooter className="mt-4">
              <Button
                type="button"
                variant="outline"
                onClick={onClose}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={handleCreate}
                disabled={isSubmitting || !selectedStackName || !hostId}
                data-testid="create-deployment-submit"
              >
                {isSubmitting ? 'Creating...' : 'Create Deployment'}
              </Button>
            </DialogFooter>
          </>
        )}

        {/* Confirmation Dialog for saving changes */}
        <AlertDialog open={showConfirmDialog} onOpenChange={setShowConfirmDialog}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Save changes to stack?</AlertDialogTitle>
              <AlertDialogDescription className="space-y-2">
                <p>
                  You've modified the stack configuration. These changes will be
                  permanently saved to the <strong>"{selectedStackName}"</strong> stack.
                </p>
                <p className="text-muted-foreground">
                  This will affect all future deployments from this stack, including
                  deployments on other hosts.
                </p>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={isSubmitting}>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={doCreateDeployment} disabled={isSubmitting}>
                {isSubmitting ? 'Saving...' : 'Save Changes & Deploy'}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </DialogContent>
    </Dialog>
  )
}
