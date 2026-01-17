/**
 * Stack Editor Component (v2.2.8+)
 *
 * Right panel for viewing and editing stack content:
 * - View/edit compose.yaml and .env files
 * - Rename stacks (inline editing)
 * - Clone and delete stacks
 * - Deploy stacks to hosts
 *
 * Used in the two-column master-detail layout on the Stacks page.
 */

import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import {
  Copy,
  Trash2,
  Pencil,
  Check,
  X,
  FolderOpen,
  Rocket,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { toast } from 'sonner'
import {
  useStack,
  useCreateStack,
  useUpdateStack,
  useRenameStack,
  useDeleteStack,
  useCopyStack,
} from '../hooks/useStacks'
import { useDeployStack } from '../hooks/useDeployments'
import { ConfigurationEditor, ConfigurationEditorHandle } from './ConfigurationEditor'
import { DeploymentProgress } from './DeploymentProgress'
import { validateStackName, MAX_STACK_NAME_LENGTH } from '../types'
import type { DeployedHost } from '../types'
import { handleApiError, getErrorMessage } from '../utils'

// Base path for stack storage (matches backend STACKS_DIR)
const STACKS_BASE_PATH = '/app/data/stacks'

type DialogType = 'delete' | 'copy' | 'save-changes' | null

interface StackEditorProps {
  selectedStackName: string | null
  hosts: Array<{ id: string; name: string }>
  deployedTo?: DeployedHost[] | undefined
  onStackChange: (name: string | null) => void
}

export function StackEditor({
  selectedStackName,
  hosts,
  deployedTo,
  onStackChange,
}: StackEditorProps) {
  // Data hooks
  const createStack = useCreateStack()
  const updateStack = useUpdateStack()
  const renameStack = useRenameStack()
  const deleteStack = useDeleteStack()
  const copyStack = useCopyStack()
  const deployStack = useDeployStack()

  // Fetch selected stack content
  const { data: selectedStack, isLoading: stackLoading } = useStack(selectedStackName)

  // Editor state
  const [stackName, setStackName] = useState('')
  const [originalName, setOriginalName] = useState('')
  const [composeYaml, setComposeYaml] = useState('')
  const [envContent, setEnvContent] = useState('')
  const [isEditingName, setIsEditingName] = useState(false)

  // Track original content for change detection
  const [originalCompose, setOriginalCompose] = useState('')
  const [originalEnv, setOriginalEnv] = useState('')

  // Deploy state
  const [hostId, setHostId] = useState('')

  // Deployment progress state
  const [isDeploying, setIsDeploying] = useState(false)
  const [activeDeploymentId, setActiveDeploymentId] = useState<string | null>(null)
  const [deployingHostName, setDeployingHostName] = useState('')

  // Dialog state
  const [activeDialog, setActiveDialog] = useState<DialogType>(null)
  const [copyDestName, setCopyDestName] = useState('')

  // Tab state
  const [activeTab, setActiveTab] = useState<'compose' | 'env'>('compose')

  // Errors
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Ref to ConfigurationEditor for YAML validation
  const configEditorRef = useRef<ConfigurationEditorHandle>(null)

  // Create mode (no stack selected)
  const isCreateMode = selectedStackName === '__new__'

  // Derived state
  const hasContentChanges = composeYaml !== originalCompose || envContent !== originalEnv
  const hasNameChange = stackName !== originalName && !isCreateMode
  const hasChanges = hasContentChanges || hasNameChange
  const isSubmitting =
    createStack.isPending ||
    updateStack.isPending ||
    renameStack.isPending ||
    deleteStack.isPending ||
    copyStack.isPending ||
    deployStack.isPending

  // Sort hosts alphabetically
  const sortedHosts = useMemo(
    () => [...hosts].sort((a, b) => a.name.localeCompare(b.name)),
    [hosts]
  )

  // Check if selected host already has this stack deployed
  const isRedeploy = useMemo(
    () => hostId && deployedTo?.some((h) => h.host_id === hostId),
    [hostId, deployedTo]
  )

  // Reset form state
  const resetForm = useCallback(() => {
    setStackName('')
    setOriginalName('')
    setComposeYaml('')
    setEnvContent('')
    setOriginalCompose('')
    setOriginalEnv('')
    setHostId('')
    setErrors({})
    setIsEditingName(false)
    setActiveDialog(null)
    setCopyDestName('')
    setActiveTab('compose')
  }, [])

  // Reset when selection changes to null
  useEffect(() => {
    if (!selectedStackName) {
      resetForm()
    }
  }, [selectedStackName, resetForm])

  // Load stack content when selected
  useEffect(() => {
    if (selectedStack) {
      const compose = selectedStack.compose_yaml || ''
      const env = selectedStack.env_content || ''
      setStackName(selectedStack.name)
      setOriginalName(selectedStack.name)
      setComposeYaml(compose)
      setEnvContent(env)
      setOriginalCompose(compose)
      setOriginalEnv(env)
      setErrors({})
      setIsEditingName(false)
    }
  }, [selectedStack])

  // Reset form when switching to create mode
  useEffect(() => {
    if (isCreateMode) {
      resetForm()
    }
  }, [isCreateMode, resetForm])

  // Set default host if only one available
  useEffect(() => {
    if (hosts.length === 1 && !hostId && hosts[0]) {
      setHostId(hosts[0].id)
    }
  }, [hosts, hostId])

  // Validate form
  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {}

    if (isCreateMode || isEditingName) {
      const nameError = validateStackName(stackName)
      if (nameError) {
        newErrors.name = nameError
      }
    }

    if (!composeYaml.trim()) {
      newErrors.compose = 'Compose YAML is required'
    }

    // Validate YAML syntax
    if (configEditorRef.current && composeYaml.trim()) {
      const validation = configEditorRef.current.validate()
      if (!validation.valid) {
        newErrors.compose = validation.error || 'Invalid YAML format'
      }
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  // Save stack (create or update)
  const handleSave = async () => {
    if (!validateForm()) return

    try {
      if (isCreateMode) {
        await createStack.mutateAsync({
          name: stackName.trim(),
          compose_yaml: composeYaml,
          env_content: envContent.trim() || null,
        })
        toast.success(`Stack "${stackName}" created`)
        onStackChange(stackName.trim())
      } else if (selectedStackName) {
        if (hasNameChange) {
          await renameStack.mutateAsync({
            name: originalName,
            new_name: stackName.trim(),
          })
        }

        const targetName = hasNameChange ? stackName.trim() : selectedStackName
        await updateStack.mutateAsync({
          name: targetName,
          compose_yaml: composeYaml,
          env_content: envContent.trim() || null,
        })

        toast.success('Stack saved')
        if (hasNameChange) {
          onStackChange(stackName.trim())
        }
      }

      setOriginalName(stackName.trim())
      setOriginalCompose(composeYaml)
      setOriginalEnv(envContent)
      setIsEditingName(false)
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error)
      if (errorMessage.includes('already exists')) {
        setErrors({ name: 'A stack with this name already exists' })
      } else {
        handleApiError(error, 'save')
      }
    }
  }

  // Delete stack
  const handleDelete = async () => {
    if (!selectedStackName || selectedStackName === '__new__') return

    try {
      await deleteStack.mutateAsync(selectedStackName)
      toast.success(`Stack "${selectedStackName}" deleted`)
      onStackChange(null)
      resetForm()
    } catch (error: unknown) {
      handleApiError(error, 'delete')
    } finally {
      setActiveDialog(null)
    }
  }

  // Copy stack
  const handleCopy = async () => {
    if (!selectedStackName || !copyDestName.trim()) return

    const validationError = validateStackName(copyDestName.trim())
    if (validationError) {
      toast.error(validationError)
      return
    }

    try {
      await copyStack.mutateAsync({
        name: selectedStackName,
        dest_name: copyDestName.trim(),
      })
      toast.success(`Stack copied to "${copyDestName}"`)
      onStackChange(copyDestName.trim())
    } catch (error: unknown) {
      handleApiError(error, 'copy')
    } finally {
      setActiveDialog(null)
      setCopyDestName('')
    }
  }

  // Execute deployment and switch to progress view
  const executeDeployment = async (deployStackName: string) => {
    const host = sortedHosts.find((h) => h.id === hostId)
    const hostName = host?.name || hostId.slice(0, 8)

    try {
      const result = await deployStack.mutateAsync({
        stack_name: deployStackName,
        host_id: hostId,
      })

      setActiveDeploymentId(result.deployment_id)
      setDeployingHostName(hostName)
      setIsDeploying(true)
    } catch (error: unknown) {
      handleApiError(error, 'deploy')
    }
  }

  // Deploy stack
  const handleDeploy = async () => {
    if (!selectedStackName || selectedStackName === '__new__' || !hostId) return

    if (hasChanges) {
      setActiveDialog('save-changes')
      return
    }

    await executeDeployment(selectedStackName)
  }

  // Deploy after saving changes
  const handleSaveAndDeploy = async () => {
    setActiveDialog(null)
    await handleSave()
    if (selectedStackName && hostId) {
      const deployStackName = hasNameChange ? stackName.trim() : selectedStackName
      await executeDeployment(deployStackName)
    }
  }

  // Name editing handlers
  const startEditingName = () => setIsEditingName(true)

  const cancelEditingName = () => {
    setStackName(originalName)
    setIsEditingName(false)
    setErrors({})
  }

  const confirmNameEdit = () => {
    const error = validateStackName(stackName)
    if (error) {
      setErrors({ name: error })
      return
    }
    setIsEditingName(false)
  }

  // Open clone dialog
  const handleOpenCloneDialog = () => {
    setCopyDestName(`${selectedStackName}-copy`)
    setActiveDialog('copy')
  }

  // Go back from deployment progress to editor
  const handleBackFromDeployment = () => {
    setIsDeploying(false)
    setActiveDeploymentId(null)
    setDeployingHostName('')
  }

  // Deployment completed
  const handleDeploymentComplete = () => {
    setIsDeploying(false)
    setActiveDeploymentId(null)
    setDeployingHostName('')
  }

  // Determine save button text
  const getSaveButtonText = (): string => {
    if (isSubmitting) return 'Saving...'
    if (isCreateMode) return 'Create Stack'
    return 'Save'
  }

  // No stack selected - show placeholder
  if (!selectedStackName) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
        <p>Select a stack from the list</p>
        <p className="text-sm mt-1">or create a new one</p>
      </div>
    )
  }

  // Show deployment progress
  if (isDeploying) {
    return (
      <DeploymentProgress
        deploymentId={activeDeploymentId}
        stackName={stackName || selectedStackName || ''}
        hostName={deployingHostName}
        onBack={handleBackFromDeployment}
        onComplete={handleDeploymentComplete}
      />
    )
  }

  // Loading state
  if (stackLoading && !isCreateMode) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Loading stack...
      </div>
    )
  }

  return (
    <>
      <div className="flex flex-col h-full overflow-hidden">
        {/* Stack name header */}
        <div className="flex items-center gap-2 mb-3 shrink-0">
          {isEditingName || isCreateMode ? (
            <div className="flex-1 flex items-center gap-2">
              <Input
                value={stackName}
                onChange={(e) => setStackName(e.target.value.toLowerCase())}
                placeholder="stack-name"
                className={cn('font-mono', errors.name && 'border-destructive')}
                maxLength={MAX_STACK_NAME_LENGTH}
                autoFocus
              />
              {!isCreateMode && (
                <>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={confirmNameEdit}
                    title="Confirm"
                  >
                    <Check className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={cancelEditingName}
                    title="Cancel"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </>
              )}
            </div>
          ) : (
            <>
              <h3 className="font-semibold text-lg font-mono">{stackName}</h3>
              <Button
                variant="ghost"
                size="icon"
                onClick={startEditingName}
                title="Rename"
                className="ml-1"
              >
                <Pencil className="h-4 w-4" />
              </Button>
              <div className="flex-1" />
            </>
          )}

          {hasChanges && <Badge variant="secondary">Modified</Badge>}
        </div>

        {/* Deployed hosts info */}
        {!isCreateMode && deployedTo && deployedTo.length > 0 && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2 shrink-0">
            <span>Deployed on:</span>
            <div className="flex flex-wrap gap-1">
              {deployedTo.map((host) => (
                <Badge key={host.host_id} variant="outline" className="font-normal">
                  {host.host_name}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {errors.name && (
          <p className="text-sm text-destructive mb-2 shrink-0">{errors.name}</p>
        )}

        {/* File path info (edit mode only) */}
        {!isCreateMode && (
          <div className="flex items-start gap-2 p-2 bg-muted/50 rounded-md text-xs text-muted-foreground mb-3 shrink-0">
            <FolderOpen className="h-3 w-3 mt-0.5 shrink-0" />
            <span className="font-mono">
              {STACKS_BASE_PATH}/{hasNameChange ? stackName : originalName}/
              {hasNameChange && (
                <span className="text-amber-500 ml-1">(will be renamed)</span>
              )}
            </span>
          </div>
        )}

        {/* Content editor with tabs */}
        <div className="flex-1 flex flex-col overflow-hidden min-h-0">
          {/* Tab buttons */}
          <div className="flex gap-1 mb-2 shrink-0">
            <Button
              type="button"
              variant={activeTab === 'compose' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveTab('compose')}
            >
              Compose
            </Button>
            <Button
              type="button"
              variant={activeTab === 'env' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveTab('env')}
            >
              Environment
            </Button>
          </div>

          {/* Tab content */}
          <div className="flex-1 min-h-0 flex flex-col">
            {activeTab === 'compose' && (
              <ConfigurationEditor
                ref={configEditorRef}
                type="stack"
                value={composeYaml}
                onChange={setComposeYaml}
                error={errors.compose}
                fillHeight
              />
            )}

            {activeTab === 'env' && (
              <Textarea
                value={envContent}
                onChange={(e) => setEnvContent(e.target.value)}
                placeholder={`# Optional .env file\nDATABASE_URL=postgres://...\nAPI_KEY=your-secret`}
                className="font-mono text-sm flex-1 min-h-0 resize-none"
              />
            )}
          </div>
        </div>

        {/* Deploy section (only for existing stacks) */}
        {!isCreateMode && (
          <div className="pt-3 mt-3 border-t shrink-0">
            <Label className="text-sm font-medium mb-2 block">Deploy to Host</Label>
            <div className="flex gap-2">
              <Select value={hostId} onValueChange={setHostId}>
                <SelectTrigger className="min-w-[250px] flex-1">
                  <SelectValue placeholder="Select a host">
                    {hostId && (sortedHosts.find((h) => h.id === hostId)?.name || hostId)}
                  </SelectValue>
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
              <Button
                onClick={handleDeploy}
                disabled={!hostId || isSubmitting}
                className="gap-2"
              >
                <Rocket className="h-4 w-4" />
                {isRedeploy ? 'Redeploy' : 'Deploy'}
              </Button>
            </div>
          </div>
        )}

        {/* Action buttons */}
        <div className="flex items-center justify-between pt-3 mt-3 border-t shrink-0">
          <div className="flex gap-2">
            {!isCreateMode && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleOpenCloneDialog}
                  disabled={isSubmitting}
                  title="Copy stack"
                >
                  <Copy className="h-4 w-4 mr-1" />
                  Clone
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setActiveDialog('delete')}
                  disabled={isSubmitting}
                  title="Delete stack"
                >
                  <Trash2 className="h-4 w-4 mr-1 text-destructive" />
                  Delete
                </Button>
              </>
            )}
          </div>

          <Button
            onClick={handleSave}
            disabled={isSubmitting || (!isCreateMode && !hasChanges)}
          >
            {getSaveButtonText()}
          </Button>
        </div>
      </div>

      {/* Delete Confirmation */}
      <AlertDialog
        open={activeDialog === 'delete'}
        onOpenChange={(open) => !open && setActiveDialog(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Stack</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete stack "<strong>{selectedStackName}</strong>"?
              This will remove the compose.yaml and .env files from the filesystem,
              along with any deployment records. Running containers will not be affected.
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Copy Dialog */}
      <Dialog
        open={activeDialog === 'copy'}
        onOpenChange={(open) => !open && setActiveDialog(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clone Stack</DialogTitle>
            <DialogDescription>
              Create a copy of "<strong>{selectedStackName}</strong>" with a new name.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="copy-dest-name">New Stack Name</Label>
              <Input
                id="copy-dest-name"
                value={copyDestName}
                onChange={(e) => setCopyDestName(e.target.value.toLowerCase())}
                placeholder="my-stack-copy"
                className="font-mono"
                maxLength={MAX_STACK_NAME_LENGTH}
              />
              <p className="text-xs text-muted-foreground">
                Lowercase letters, numbers, hyphens, and underscores only
              </p>
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setActiveDialog(null)}>
              Cancel
            </Button>
            <Button onClick={handleCopy} disabled={!copyDestName.trim() || isSubmitting}>
              {isSubmitting ? 'Copying...' : 'Clone Stack'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Save Changes Before Deploy */}
      <AlertDialog
        open={activeDialog === 'save-changes'}
        onOpenChange={(open) => !open && setActiveDialog(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Save changes before deploying?</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved changes to this stack. Would you like to save them
              before deploying?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleSaveAndDeploy}>
              Save & Deploy
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
