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
  RefreshCw,
  Square,
  Plus,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
  useDeleteEnvFile,
} from '../hooks/useStacks'
import { useStackAction } from '../hooks/useDeployments'
import type { StackAction } from '../hooks/useDeployments'
import { usePortConflicts } from '../hooks/usePortConflicts'
import { ConfigurationEditor, ConfigurationEditorHandle } from './ConfigurationEditor'
import { DeploymentProgress } from './DeploymentProgress'
import { PortConflictBanner } from './PortConflictBanner'
import { validateStackName, MAX_STACK_NAME_LENGTH } from '../types'
import type { DeployedHost, PortConflict } from '../types'
import { handleApiError, getErrorMessage, envFilesEqual, validateEnvFileName } from '../utils'
import { useAuth } from '@/features/auth/AuthContext'

// Base path for stack storage (matches backend STACKS_DIR)
const STACKS_BASE_PATH = '/app/data/stacks'

type DialogType = 'delete' | 'copy' | 'save-changes' | 'remove-confirm' | 'add-env-file' | 'remove-env-file' | null

interface PendingActionState {
  action: StackAction
  removeVolumes: boolean
}

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
  const { hasCapability } = useAuth()
  const canEdit = hasCapability('stacks.edit')
  const canDeploy = hasCapability('stacks.deploy')
  const canViewEnv = hasCapability('stacks.view_env')

  // Data hooks
  const createStack = useCreateStack()
  const updateStack = useUpdateStack()
  const renameStack = useRenameStack()
  const deleteStack = useDeleteStack()
  const copyStack = useCopyStack()
  const stackAction = useStackAction()
  const deleteEnvFile = useDeleteEnvFile()

  // Fetch selected stack content
  const { data: selectedStack, isLoading: stackLoading } = useStack(selectedStackName)

  // Editor state
  const [stackName, setStackName] = useState('')
  const [originalName, setOriginalName] = useState('')
  const [composeYaml, setComposeYaml] = useState('')
  const [envFiles, setEnvFiles] = useState<Record<string, string>>({})
  const [isEditingName, setIsEditingName] = useState(false)

  // Track original content for change detection
  const [originalCompose, setOriginalCompose] = useState('')
  const [originalEnvFiles, setOriginalEnvFiles] = useState<Record<string, string>>({})

  // Deploy state
  const [hostId, setHostId] = useState('')

  // Deployment progress state
  const [isDeploying, setIsDeploying] = useState(false)
  const [activeDeploymentId, setActiveDeploymentId] = useState<string | null>(null)
  const [deployingHostName, setDeployingHostName] = useState('')
  const [activeAction, setActiveAction] = useState<StackAction>('up')

  // Dialog state
  const [activeDialog, setActiveDialog] = useState<DialogType>(null)
  const [copyDestName, setCopyDestName] = useState('')
  const [newEnvFileName, setNewEnvFileName] = useState('')
  const [envFileNameError, setEnvFileNameError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<PendingActionState | null>(null)
  const [envFileToRemove, setEnvFileToRemove] = useState<string | null>(null)

  // Tab state
  const [activeTab, setActiveTab] = useState<string>('compose')

  // Env-file tabs shown when the user can view env: always offer a default .env
  // plus any env files the stack already has. A .env that isn't in envFiles stays
  // virtual (empty) until edited, so it never trips change detection nor writes
  // an empty file on save.
  const envTabNames = useMemo(
    () => (canViewEnv ? Array.from(new Set(['.env', ...Object.keys(envFiles)])) : []),
    [canViewEnv, envFiles]
  )

  // Reset to compose if the active env tab is no longer available
  useEffect(() => {
    if (activeTab !== 'compose' && !envTabNames.includes(activeTab)) {
      setActiveTab('compose')
    }
  }, [activeTab, envTabNames])

  // Errors
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Ref to ConfigurationEditor for YAML validation
  const configEditorRef = useRef<ConfigurationEditorHandle>(null)

  // Create mode (no stack selected)
  const isCreateMode = selectedStackName === '__new__'

  // Derived state
  const hasContentChanges = composeYaml !== originalCompose || !envFilesEqual(envFiles, originalEnvFiles)
  const hasNameChange = stackName !== originalName && !isCreateMode
  const hasChanges = hasContentChanges || hasNameChange
  const isEnvFileToRemovePersisted =
    envFileToRemove != null &&
    Object.prototype.hasOwnProperty.call(originalEnvFiles, envFileToRemove)
  const isSubmitting =
    createStack.isPending ||
    updateStack.isPending ||
    renameStack.isPending ||
    deleteStack.isPending ||
    copyStack.isPending ||
    stackAction.isPending ||
    deleteEnvFile.isPending

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

  const {
    conflicts: portConflicts,
    isLoading: portCheckLoading,
    error: portCheckError,
    recheck: recheckPorts,
  } = usePortConflicts({
    stackName: selectedStackName && selectedStackName !== '__new__' ? selectedStackName : null,
    hostId: hostId || null,
  })

  const [showPortConfirm, setShowPortConfirm] = useState(false)

  // Tracks which stack identity the editor state was last initialized from, so a
  // background refetch of the SAME stack does not clobber unsaved edits.
  const loadedStackNameRef = useRef<string | null>(null)

  // Reset form state
  const resetForm = useCallback(() => {
    loadedStackNameRef.current = null
    setStackName('')
    setOriginalName('')
    setComposeYaml('')
    setEnvFiles({})
    setOriginalCompose('')
    setOriginalEnvFiles({})
    setHostId('')
    setErrors({})
    setIsEditingName(false)
    setActiveDialog(null)
    setCopyDestName('')
    setNewEnvFileName('')
    setEnvFileNameError(null)
    setEnvFileToRemove(null)
    setActiveTab('compose')
  }, [])

  // Reset when selection changes to null
  useEffect(() => {
    if (!selectedStackName) {
      resetForm()
    }
  }, [selectedStackName, resetForm])

  // Load stack content when a different stack is selected (first load / switch).
  // Guarded by identity so a same-stack refetch (e.g. after an env-file delete
  // invalidates the query) does not overwrite the user's unsaved edits.
  useEffect(() => {
    if (selectedStack && loadedStackNameRef.current !== selectedStack.name) {
      loadedStackNameRef.current = selectedStack.name
      const compose = selectedStack.compose_yaml || ''
      const files = selectedStack.env_files || {}
      setStackName(selectedStack.name)
      setOriginalName(selectedStack.name)
      setComposeYaml(compose)
      setEnvFiles(files)
      setOriginalCompose(compose)
      setOriginalEnvFiles(files)
      setErrors({})
      setIsEditingName(false)
      setActiveTab('compose')
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

  const handleSave = async (): Promise<boolean> => {
    if (!validateForm()) return false

    try {
      if (isCreateMode) {
        await createStack.mutateAsync({
          name: stackName.trim(),
          compose_yaml: composeYaml,
          env_files: envFiles,
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
          env_files: envFiles,
        })

        toast.success('Stack saved')
        if (hasNameChange) {
          onStackChange(stackName.trim())
        }
      }

      setOriginalName(stackName.trim())
      setOriginalCompose(composeYaml)
      setOriginalEnvFiles(envFiles)
      setIsEditingName(false)
      return true
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error)
      if (errorMessage.includes('already exists')) {
        setErrors({ name: 'A stack with this name already exists' })
      } else {
        handleApiError(error, 'save')
      }
      return false
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

  // Execute stack action and switch to progress view
  const executeDeployment = async (
    deployStackName: string,
    action: StackAction = 'up',
    removeVolumes = false,
  ) => {
    const host = sortedHosts.find((h) => h.id === hostId)
    const hostName = host?.name || hostId.slice(0, 8)

    try {
      const result = await stackAction.mutateAsync({
        stack_name: deployStackName,
        host_id: hostId,
        action,
        remove_volumes: removeVolumes,
      })

      setActiveAction(action)
      setActiveDeploymentId(result.deployment_id)
      setDeployingHostName(hostName)
      setIsDeploying(true)
    } catch (error: unknown) {
      const actionLabel = { down: 'stop', restart: 'restart', up: 'deploy' }[action]
      handleApiError(error, actionLabel)
    }
  }

  // Execute a stack action with unsaved-changes check and remove confirmation
  const handleAction = async (action: StackAction = 'up', removeVolumes = false) => {
    if (!selectedStackName || selectedStackName === '__new__' || !hostId) return

    if (hasChanges) {
      setPendingAction({ action, removeVolumes })
      setActiveDialog('save-changes')
      return
    }

    // Destructive remove always requires confirmation
    if (removeVolumes) {
      setActiveDialog('remove-confirm')
      return
    }

    await executeDeployment(selectedStackName, action, removeVolumes)
  }

  // Deploy stack (convenience for deploy button)
  const executeDeploy = () => handleAction('up')

  // Guarded deploy: re-check port conflicts fresh, and if any remain, ask
  // the user before proceeding. Docker is still the final gate.
  const onDeployClick = async () => {
    if (!hostId || !selectedStackName || selectedStackName === '__new__') return
    let fresh: PortConflict[] = []
    try {
      fresh = await recheckPorts()
    } catch {
      await executeDeploy()
      return
    }
    if (fresh.length > 0) {
      setShowPortConfirm(true)
      return
    }
    await executeDeploy()
  }

  // Save changes, then either show remove-confirm dialog or execute the pending action
  const handleSaveAndDeploy = async () => {
    const actionToExecute = pendingAction ?? { action: 'up' as StackAction, removeVolumes: false }
    setActiveDialog(null)
    setPendingAction(null)
    const saved = await handleSave()
    if (!saved || !selectedStackName || !hostId) return
    // Destructive remove requires confirmation even after saving
    if (actionToExecute.removeVolumes) {
      setActiveDialog('remove-confirm')
      return
    }
    const deployStackName = hasNameChange ? stackName.trim() : selectedStackName
    await executeDeployment(deployStackName, actionToExecute.action, actionToExecute.removeVolumes)
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

  // Open the add-env-file dialog
  const openAddEnvFileDialog = () => {
    setNewEnvFileName('')
    setEnvFileNameError(null)
    setActiveDialog('add-env-file')
  }

  // Add a new (empty) env file tab after validating its name
  const handleAddEnvFile = () => {
    const raw = newEnvFileName.trim()
    const validationError = validateEnvFileName(raw)
    if (validationError) {
      setEnvFileNameError(validationError)
      return
    }
    const fname = raw.startsWith('./') ? raw.slice(2) : raw
    if (envTabNames.includes(fname)) {
      setEnvFileNameError('A tab for this file already exists')
      return
    }
    setEnvFiles((prev) => ({ ...prev, [fname]: '' }))
    setActiveTab(fname)
    setActiveDialog(null)
  }

  // Remove an env file tab (persisted or unsaved)
  const handleRemoveEnvFile = async () => {
    const fname = envFileToRemove
    if (!fname) return
    const isPersisted = Object.prototype.hasOwnProperty.call(originalEnvFiles, fname)
    if (isPersisted) {
      if (!selectedStackName || selectedStackName === '__new__') return
      try {
        await deleteEnvFile.mutateAsync({ name: selectedStackName, filename: fname })
      } catch (error: unknown) {
        handleApiError(error, 'remove env file')
        setActiveDialog(null)
        setEnvFileToRemove(null)
        return
      }
      setOriginalEnvFiles((prev) => {
        const next = { ...prev }
        delete next[fname]
        return next
      })
    }
    setEnvFiles((prev) => {
      const next = { ...prev }
      delete next[fname]
      return next
    })
    if (activeTab === fname) setActiveTab('compose')
    setActiveDialog(null)
    setEnvFileToRemove(null)
  }

  // Reset deployment progress state (used by both back and complete actions)
  const resetDeploymentState = () => {
    setIsDeploying(false)
    setActiveDeploymentId(null)
    setDeployingHostName('')
    setActiveAction('up')
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
        action={activeAction}
        onBack={resetDeploymentState}
        onComplete={resetDeploymentState}
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
            <fieldset disabled={!canEdit} className="flex-1 flex items-center gap-2 disabled:opacity-60">
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
            </fieldset>
          ) : (
            <>
              <h3 className="font-semibold text-lg font-mono">{stackName}</h3>
              <Button
                variant="ghost"
                size="icon"
                onClick={startEditingName}
                disabled={!canEdit}
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
          <div className="flex gap-1 mb-2 shrink-0 flex-wrap">
            <Button
              type="button"
              variant={activeTab === 'compose' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveTab('compose')}
            >
              Compose
            </Button>
            {canViewEnv &&
              envTabNames.map((fname) => {
                const removable = Object.prototype.hasOwnProperty.call(envFiles, fname)
                return (
                  <div key={fname} className="flex items-center">
                    <Button
                      type="button"
                      variant={activeTab === fname ? 'default' : 'ghost'}
                      size="sm"
                      className="font-mono"
                      onClick={() => setActiveTab(fname)}
                    >
                      {fname}
                    </Button>
                    {removable && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 -ml-1"
                        disabled={!canEdit || deleteEnvFile.isPending}
                        title={`Remove ${fname}`}
                        onClick={() => {
                          setEnvFileToRemove(fname)
                          setActiveDialog('remove-env-file')
                        }}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                )
              })}
            {canViewEnv && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={openAddEnvFileDialog}
                disabled={!canEdit}
                title="Add env file"
                className="px-2"
              >
                <Plus className="h-4 w-4" />
              </Button>
            )}
          </div>

          {/* Tab content */}
          <fieldset disabled={!canEdit} className="flex-1 min-h-0 flex flex-col disabled:opacity-60">
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

            {canViewEnv && activeTab !== 'compose' && envTabNames.includes(activeTab) && (
              <ConfigurationEditor
                type="env"
                value={envFiles[activeTab] ?? ''}
                onChange={(value) =>
                  setEnvFiles((prev) => ({ ...prev, [activeTab]: value }))
                }
                fillHeight
              />
            )}
          </fieldset>
        </div>

        {/* Deploy section (only for existing stacks) */}
        {!isCreateMode && (
          <fieldset disabled={!canDeploy} className="pt-3 mt-3 border-t shrink-0 disabled:opacity-60">
            <Label className="text-sm font-medium mb-2 block">Deploy to Host</Label>
            {hostId && selectedStackName && selectedStackName !== '__new__' && (
              <div className="mb-2">
                <PortConflictBanner
                  conflicts={portConflicts}
                  isLoading={portCheckLoading}
                  error={portCheckError}
                  hostName={sortedHosts.find((h) => h.id === hostId)?.name || hostId.slice(0, 8)}
                />
              </div>
            )}
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
                onClick={onDeployClick}
                disabled={!hostId || isSubmitting}
                className="gap-2"
              >
                <Rocket className="h-4 w-4" />
                {isRedeploy ? 'Redeploy' : 'Deploy'}
              </Button>
              {isRedeploy && (
                <>
                  <Button
                    variant="outline"
                    onClick={() => handleAction('restart')}
                    disabled={!hostId || isSubmitting}
                    className="gap-2"
                    title="Restart stack (down then up, no image pull)"
                  >
                    <RefreshCw className="h-4 w-4" />
                    Restart
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => handleAction('down')}
                    disabled={!hostId || isSubmitting}
                    className="gap-2"
                    title="Stop and remove containers and networks"
                  >
                    <Square className="h-4 w-4" />
                    Stop
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => handleAction('down', true)}
                    disabled={!hostId || isSubmitting}
                    className="gap-2 text-destructive border-destructive/50 hover:bg-destructive/10"
                    title="Stop, remove containers, networks, and volumes"
                  >
                    <Trash2 className="h-4 w-4" />
                    Remove
                  </Button>
                </>
              )}
            </div>
          </fieldset>
        )}

        {/* Action buttons */}
        <div className="flex items-center justify-between pt-3 mt-3 border-t shrink-0">
          <fieldset disabled={!canEdit} className="flex items-center gap-1 disabled:opacity-60">
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
          </fieldset>

          <fieldset disabled={!canEdit} className="disabled:opacity-60">
            <Button
              onClick={handleSave}
              disabled={isSubmitting || (!isCreateMode && !hasChanges)}
            >
              {getSaveButtonText()}
            </Button>
          </fieldset>
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
            <fieldset disabled={!canEdit} className="disabled:opacity-60">
              <AlertDialogAction
                onClick={handleDelete}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                Delete
              </AlertDialogAction>
            </fieldset>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Port conflict confirmation */}
      <AlertDialog open={showPortConfirm} onOpenChange={setShowPortConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Port conflicts detected</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2">
                <p>
                  The following host ports are already in use on this target.
                  Deploying anyway may fail when Docker tries to bind them.
                </p>
                <ul className="space-y-0.5 text-sm">
                  {portConflicts.map((c) => (
                    <li key={`${c.port}-${c.protocol}-${c.container_id}`}>
                      Port <code className="rounded bg-muted px-1">{c.port}/{c.protocol}</code>
                      {' '}— {c.container_name}
                    </li>
                  ))}
                </ul>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                setShowPortConfirm(false)
                await executeDeploy()
              }}
            >
              Deploy anyway
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

          <fieldset disabled={!canEdit} className="space-y-4 disabled:opacity-60">
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
          </fieldset>

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setActiveDialog(null)}>
              Cancel
            </Button>
            <fieldset disabled={!canEdit} className="disabled:opacity-60">
              <Button onClick={handleCopy} disabled={!copyDestName.trim() || isSubmitting}>
                {isSubmitting ? 'Copying...' : 'Clone Stack'}
              </Button>
            </fieldset>
          </div>
        </DialogContent>
      </Dialog>

      {/* Add Env File Dialog */}
      <Dialog
        open={activeDialog === 'add-env-file'}
        onOpenChange={(open) => !open && setActiveDialog(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Env File</DialogTitle>
            <DialogDescription>
              Add an environment file to this stack. Reference it from your compose
              with <code className="bg-muted px-1 rounded">env_file:</code> to load it
              into a service.
            </DialogDescription>
          </DialogHeader>

          <fieldset disabled={!canEdit} className="space-y-4 disabled:opacity-60">
            <div className="space-y-2 py-2">
              <Label htmlFor="new-env-file-name">Filename</Label>
              <Input
                id="new-env-file-name"
                value={newEnvFileName}
                onChange={(e) => {
                  setNewEnvFileName(e.target.value)
                  setEnvFileNameError(null)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleAddEnvFile()
                  }
                }}
                placeholder=".db.env"
                className={cn('font-mono', envFileNameError && 'border-destructive')}
                autoFocus
              />
              {envFileNameError ? (
                <p className="text-xs text-destructive">{envFileNameError}</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  A bare filename in the stack directory (no slashes), e.g. .env or .db.env
                </p>
              )}
            </div>
          </fieldset>

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setActiveDialog(null)}>
              Cancel
            </Button>
            <fieldset disabled={!canEdit} className="disabled:opacity-60">
              <Button onClick={handleAddEnvFile} disabled={!newEnvFileName.trim()}>
                Add File
              </Button>
            </fieldset>
          </div>
        </DialogContent>
      </Dialog>

      {/* Remove Confirmation */}
      <AlertDialog
        open={activeDialog === 'remove-confirm'}
        onOpenChange={(open) => !open && setActiveDialog(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove Stack</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to remove stack "<strong>{selectedStackName}</strong>"
              from <strong>{sortedHosts.find((h) => h.id === hostId)?.name || hostId}</strong>?
              This will stop and remove all containers, networks, <strong>and volumes</strong>.
              Data stored in volumes will be permanently lost. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setActiveDialog(null)
                executeDeployment(selectedStackName, 'down', true)
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
            <fieldset disabled={!canEdit || !canDeploy} className="disabled:opacity-60">
              <AlertDialogAction onClick={handleSaveAndDeploy}>
                Save & Deploy
              </AlertDialogAction>
            </fieldset>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Remove Env File Confirmation */}
      <AlertDialog
        open={activeDialog === 'remove-env-file'}
        onOpenChange={(open) => {
          if (!open) {
            setActiveDialog(null)
            setEnvFileToRemove(null)
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {isEnvFileToRemovePersisted ? 'Delete env file' : 'Remove env file'}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2">
                {isEnvFileToRemovePersisted ? (
                  <>
                    <p>
                      Delete &ldquo;<strong className="font-mono">{envFileToRemove}</strong>&rdquo; from
                      this stack? This permanently removes the file from the stack directory.
                    </p>
                    <p className="text-amber-500">
                      If your compose references this file with{' '}
                      <code className="bg-muted px-1 rounded">env_file:</code>, remove that line
                      too, or it will reappear empty and deploys may fail.
                    </p>
                  </>
                ) : (
                  <p>
                    Remove &ldquo;<strong className="font-mono">{envFileToRemove}</strong>&rdquo;? It hasn&apos;t
                    been saved yet.
                  </p>
                )}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <fieldset disabled={!canEdit} className="disabled:opacity-60">
              <AlertDialogAction
                onClick={handleRemoveEnvFile}
                disabled={deleteEnvFile.isPending}
                className={isEnvFileToRemovePersisted ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90' : undefined}
              >
                {deleteEnvFile.isPending ? 'Deleting...' : isEnvFileToRemovePersisted ? 'Delete file' : 'Remove file'}
              </AlertDialogAction>
            </fieldset>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
