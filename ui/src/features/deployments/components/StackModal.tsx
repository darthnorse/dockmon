/**
 * Stack Modal Component (v2.2.8+)
 *
 * Consolidated modal for all stack operations:
 * - View/edit stack content (compose.yaml, .env)
 * - Rename stacks
 * - Clone stacks
 * - Delete stacks
 * - Deploy stacks to hosts
 *
 * Two-column layout:
 * - Left: Searchable stack list
 * - Right: Stack editor with actions
 *
 * Resizable with localStorage persistence.
 */

import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import {
  Search,
  Plus,
  Copy,
  Trash2,
  Pencil,
  Check,
  X,
  FolderOpen,
  Rocket,
  GripVertical,
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
  useStacks,
  useStack,
  useCreateStack,
  useUpdateStack,
  useRenameStack,
  useDeleteStack,
  useCopyStack,
} from '../hooks/useStacks'
import { useCreateDeployment, useDeployments } from '../hooks/useDeployments'
import { ConfigurationEditor, ConfigurationEditorHandle } from './ConfigurationEditor'
import { validateStackName, MAX_STACK_NAME_LENGTH } from '../types'

// Base path for stack storage (matches backend STACKS_DIR)
const STACKS_BASE_PATH = '/app/data/stacks'

// Modal size storage
const MODAL_SIZE_KEY = 'dockmon-stack-modal-size'
const DEFAULT_WIDTH = 1400
const DEFAULT_HEIGHT = 800
const MIN_WIDTH = 800
const MIN_HEIGHT = 500
const MAX_WIDTH_VW = 95
const MAX_HEIGHT_VH = 95

interface ModalSize {
  width: number
  height: number
}

function loadModalSize(): ModalSize {
  try {
    const saved = localStorage.getItem(MODAL_SIZE_KEY)
    if (saved) {
      const parsed = JSON.parse(saved)
      if (parsed.width && parsed.height) {
        return {
          width: Math.max(MIN_WIDTH, Math.min(parsed.width, window.innerWidth * MAX_WIDTH_VW / 100)),
          height: Math.max(MIN_HEIGHT, Math.min(parsed.height, window.innerHeight * MAX_HEIGHT_VH / 100)),
        }
      }
    }
  } catch {
    // Ignore
  }
  return { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT }
}

function saveModalSize(size: ModalSize): void {
  try {
    localStorage.setItem(MODAL_SIZE_KEY, JSON.stringify(size))
  } catch {
    // Ignore
  }
}

interface StackModalProps {
  isOpen: boolean
  onClose: () => void
  hosts?: Array<{ id: string; name: string }>
  initialStackName?: string | null
}

type DialogType = 'delete' | 'copy' | 'save-changes' | null

export function StackModal({
  isOpen,
  onClose,
  hosts = [],
  initialStackName = null,
}: StackModalProps) {
  // Modal size state
  const [modalSize, setModalSize] = useState<ModalSize>(loadModalSize)
  const [isResizing, setIsResizing] = useState(false)
  const resizeRef = useRef<{ startX: number; startY: number; startWidth: number; startHeight: number } | null>(null)

  // Data hooks
  const { data: stacks, isLoading: stacksLoading } = useStacks()
  const { data: deployments, isLoading: deploymentsLoading } = useDeployments()
  const createStack = useCreateStack()
  const updateStack = useUpdateStack()
  const renameStack = useRenameStack()
  const deleteStack = useDeleteStack()
  const copyStack = useCopyStack()
  const createDeployment = useCreateDeployment()

  // Selection state
  const [selectedStackName, setSelectedStackName] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

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

  // Check if selected stack is already deployed to selected host
  const isRedeployment = useMemo(() => {
    // Don't show "Redeploy" while still loading deployments data
    if (deploymentsLoading || !deployments || !selectedStackName || selectedStackName === '__new__' || !hostId) {
      return false
    }
    return deployments.some(
      (d) => d.stack_name === selectedStackName && d.host_id === hostId
    )
  }, [deploymentsLoading, deployments, selectedStackName, hostId])

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
    createDeployment.isPending

  // Filter stacks by search query
  const filteredStacks = useMemo(() => {
    if (!stacks) return []
    if (!searchQuery.trim()) return stacks
    return stacks.filter((s) =>
      s.name.toLowerCase().includes(searchQuery.toLowerCase())
    )
  }, [stacks, searchQuery])

  // Sort hosts alphabetically
  const sortedHosts = useMemo(
    () => [...hosts].sort((a, b) => a.name.localeCompare(b.name)),
    [hosts]
  )

  // Resize handlers
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
    resizeRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startWidth: modalSize.width,
      startHeight: modalSize.height,
    }
  }, [modalSize])

  const handleResizeMove = useCallback((e: MouseEvent) => {
    if (!isResizing || !resizeRef.current) return

    const deltaX = e.clientX - resizeRef.current.startX
    const deltaY = e.clientY - resizeRef.current.startY

    const maxWidth = window.innerWidth * MAX_WIDTH_VW / 100
    const maxHeight = window.innerHeight * MAX_HEIGHT_VH / 100

    const newWidth = Math.max(MIN_WIDTH, Math.min(resizeRef.current.startWidth + deltaX, maxWidth))
    const newHeight = Math.max(MIN_HEIGHT, Math.min(resizeRef.current.startHeight + deltaY, maxHeight))

    setModalSize({ width: newWidth, height: newHeight })
  }, [isResizing])

  const handleResizeEnd = useCallback(() => {
    if (isResizing) {
      setIsResizing(false)
      saveModalSize(modalSize)
      resizeRef.current = null
    }
  }, [isResizing, modalSize])

  // Attach resize listeners
  useEffect(() => {
    if (isResizing) {
      document.addEventListener('mousemove', handleResizeMove)
      document.addEventListener('mouseup', handleResizeEnd)
      return () => {
        document.removeEventListener('mousemove', handleResizeMove)
        document.removeEventListener('mouseup', handleResizeEnd)
      }
    }
    return undefined
  }, [isResizing, handleResizeMove, handleResizeEnd])

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

  // Reset when modal closes
  useEffect(() => {
    if (!isOpen) {
      setSelectedStackName(null)
      setSearchQuery('')
      resetForm()
    }
  }, [isOpen, resetForm])

  // Set initial stack selection
  useEffect(() => {
    if (isOpen && initialStackName) {
      setSelectedStackName(initialStackName)
    }
  }, [isOpen, initialStackName])

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

  // Set default host if only one available
  useEffect(() => {
    if (hosts.length === 1 && !hostId && hosts[0]) {
      setHostId(hosts[0].id)
    }
  }, [hosts, hostId])

  // Handle stack selection
  const handleStackSelect = (name: string) => {
    if (name === selectedStackName) return

    if (name === '__new__') {
      resetForm()
      setSelectedStackName('__new__')
    } else {
      resetForm()
      setSelectedStackName(name)
    }
  }

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
        setSelectedStackName(stackName.trim())
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
          setSelectedStackName(stackName.trim())
        }
      }

      setOriginalName(stackName.trim())
      setOriginalCompose(composeYaml)
      setOriginalEnv(envContent)
      setIsEditingName(false)
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      if (errorMessage.includes('already exists')) {
        setErrors({ name: 'A stack with this name already exists' })
      } else {
        toast.error(`Failed to save: ${errorMessage}`)
      }
    }
  }

  // Delete stack
  const handleDelete = async () => {
    if (!selectedStackName || selectedStackName === '__new__') return

    try {
      await deleteStack.mutateAsync(selectedStackName)
      toast.success(`Stack "${selectedStackName}" deleted`)
      setSelectedStackName(null)
      resetForm()
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      toast.error(`Failed to delete: ${errorMessage}`)
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
      setSelectedStackName(copyDestName.trim())
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      toast.error(`Failed to copy: ${errorMessage}`)
    } finally {
      setActiveDialog(null)
      setCopyDestName('')
    }
  }

  // Deploy stack
  const handleDeploy = async () => {
    if (!selectedStackName || selectedStackName === '__new__' || !hostId) return

    if (hasChanges) {
      setActiveDialog('save-changes')
      return
    }

    try {
      await createDeployment.mutateAsync({
        stack_name: selectedStackName,
        host_id: hostId,
      })
      toast.success(`Deploying "${selectedStackName}"...`)
      onClose()
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      toast.error(`Failed to deploy: ${errorMessage}`)
    }
  }

  // Deploy after saving changes
  const handleSaveAndDeploy = async () => {
    setActiveDialog(null)
    await handleSave()
    if (selectedStackName && hostId) {
      try {
        await createDeployment.mutateAsync({
          stack_name: hasNameChange ? stackName.trim() : selectedStackName,
          host_id: hostId,
        })
        toast.success(`Deploying "${stackName}"...`)
        onClose()
      } catch (error: unknown) {
        const errorMessage = error instanceof Error ? error.message : String(error)
        toast.error(`Failed to deploy: ${errorMessage}`)
      }
    }
  }

  // Start editing name
  const startEditingName = () => {
    setIsEditingName(true)
  }

  // Cancel editing name
  const cancelEditingName = () => {
    setStackName(originalName)
    setIsEditingName(false)
    setErrors({})
  }

  // Confirm name edit
  const confirmNameEdit = () => {
    const error = validateStackName(stackName)
    if (error) {
      setErrors({ name: error })
      return
    }
    setIsEditingName(false)
  }

  // Render stack list
  const renderStackList = () => {
    if (stacksLoading) {
      return <p className="text-sm text-muted-foreground p-2">Loading stacks...</p>
    }

    return (
      <>
        {filteredStacks.map((stack) => (
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
            <span className="truncate font-mono text-sm">{stack.name}</span>
            {stack.deployment_count > 0 && (
              <Badge
                variant={selectedStackName === stack.name ? 'secondary' : 'outline'}
                className="ml-2 shrink-0"
              >
                {stack.deployment_count}
              </Badge>
            )}
          </button>
        ))}

        {filteredStacks.length === 0 && stacks && stacks.length > 0 && (
          <p className="text-sm text-muted-foreground p-2">
            No stacks match "{searchQuery}"
          </p>
        )}

        {(!stacks || stacks.length === 0) && (
          <p className="text-sm text-muted-foreground p-2">
            No stacks yet. Create your first stack.
          </p>
        )}
      </>
    )
  }

  // Calculate editor height based on modal size
  const editorHeight = modalSize.height - 320 // Account for header, tabs, buttons, deploy section

  return (
    <>
      <Dialog open={isOpen} onOpenChange={onClose}>
        <DialogContent
          className="overflow-hidden p-0 flex flex-col"
          style={{
            width: `min(${modalSize.width}px, ${MAX_WIDTH_VW}vw)`,
            height: `min(${modalSize.height}px, ${MAX_HEIGHT_VH}vh)`,
            maxWidth: 'none',
            maxHeight: 'none',
          }}
          data-testid="stack-modal"
        >
          <DialogHeader className="px-6 pt-6 pb-2">
            <DialogTitle>Stacks</DialogTitle>
            <DialogDescription>
              Manage and deploy Docker Compose configurations
            </DialogDescription>
          </DialogHeader>

          <div className="flex-1 grid grid-cols-[300px_1fr] gap-6 px-6 pb-6 overflow-hidden">
            {/* LEFT COLUMN: Stack list */}
            <div className="flex flex-col border-r pr-4 pt-1 pl-1 overflow-hidden">
              {/* New Stack button */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleStackSelect('__new__')}
                className={cn(
                  'mb-3 gap-2 shrink-0',
                  isCreateMode && 'bg-primary text-primary-foreground hover:bg-primary/90'
                )}
              >
                <Plus className="h-4 w-4" />
                New Stack
              </Button>

              {/* Search input */}
              <div className="relative mb-3 shrink-0">
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
            </div>

            {/* RIGHT COLUMN: Stack editor */}
            <div className="flex flex-col overflow-hidden">
              {selectedStackName ? (
                stackLoading && !isCreateMode ? (
                  <div className="flex items-center justify-center h-full text-muted-foreground">
                    Loading stack...
                  </div>
                ) : (
                  <>
                    {/* Stack name header */}
                    <div className="flex items-center gap-2 mb-3 shrink-0">
                      {isEditingName || isCreateMode ? (
                        <div className="flex-1 flex items-center gap-2">
                          <Input
                            value={stackName}
                            onChange={(e) => setStackName(e.target.value.toLowerCase())}
                            placeholder="stack-name"
                            className={cn(
                              'font-mono',
                              errors.name && 'border-destructive'
                            )}
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
                          <h3 className="font-semibold text-lg font-mono">
                            {stackName}
                          </h3>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={startEditingName}
                            title="Rename"
                            className="ml-1"
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <div className="flex-1" /> {/* Spacer */}
                        </>
                      )}

                      {hasChanges && (
                        <Badge variant="secondary">Modified</Badge>
                      )}
                    </div>

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

                    {/* Content editor with simple tabs */}
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

                      {/* Tab content - fills remaining space */}
                      <div className="flex-1 min-h-0">
                        {activeTab === 'compose' && (
                          <ConfigurationEditor
                            ref={configEditorRef}
                            type="stack"
                            value={composeYaml}
                            onChange={setComposeYaml}
                            error={errors.compose}
                            rows={Math.max(10, Math.floor(editorHeight / 22))}
                          />
                        )}

                        {activeTab === 'env' && (
                          <Textarea
                            value={envContent}
                            onChange={(e) => setEnvContent(e.target.value)}
                            placeholder={`# Optional .env file\nDATABASE_URL=postgres://...\nAPI_KEY=your-secret`}
                            className="font-mono text-sm h-full resize-none"
                            style={{ minHeight: `${Math.max(200, editorHeight)}px` }}
                          />
                        )}
                      </div>
                    </div>

                    {/* Deploy section (only for existing stacks) */}
                    {!isCreateMode && (
                      <div className="pt-3 mt-3 border-t shrink-0">
                        <Label className="text-sm font-medium mb-2 block">
                          Deploy to Host
                        </Label>
                        <div className="flex gap-2">
                          <Select value={hostId} onValueChange={setHostId}>
                            <SelectTrigger className="min-w-[250px] flex-1">
                              <SelectValue placeholder="Select a host">
                                {hostId && (sortedHosts.find(h => h.id === hostId)?.name || hostId)}
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
                            {isRedeployment ? 'Redeploy' : 'Deploy'}
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
                              onClick={() => {
                                setCopyDestName(`${selectedStackName}-copy`)
                                setActiveDialog('copy')
                              }}
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
                              disabled={isSubmitting || (selectedStack?.deployment_count ?? 0) > 0}
                              title={
                                (selectedStack?.deployment_count ?? 0) > 0
                                  ? 'Delete deployments first'
                                  : 'Delete stack'
                              }
                            >
                              <Trash2 className="h-4 w-4 mr-1 text-destructive" />
                              Delete
                            </Button>
                          </>
                        )}
                      </div>

                      <div className="flex gap-2">
                        <Button variant="outline" onClick={onClose}>
                          Close
                        </Button>
                        <Button
                          onClick={handleSave}
                          disabled={isSubmitting || (!isCreateMode && !hasChanges)}
                        >
                          {isSubmitting
                            ? 'Saving...'
                            : isCreateMode
                              ? 'Create Stack'
                              : 'Save'}
                        </Button>
                      </div>
                    </div>
                  </>
                )
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                  <p>Select a stack from the list</p>
                  <p className="text-sm mt-1">or create a new one</p>
                </div>
              )}
            </div>
          </div>

          {/* Resize handle */}
          <div
            className="absolute bottom-0 right-0 w-6 h-6 cursor-se-resize flex items-center justify-center text-muted-foreground hover:text-foreground"
            onMouseDown={handleResizeStart}
            title="Drag to resize"
          >
            <GripVertical className="h-4 w-4 rotate-[-45deg]" />
          </div>
        </DialogContent>
      </Dialog>

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
              This will remove the compose.yaml and .env files from the filesystem.
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
            <Button
              onClick={handleCopy}
              disabled={!copyDestName.trim() || isSubmitting}
            >
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
