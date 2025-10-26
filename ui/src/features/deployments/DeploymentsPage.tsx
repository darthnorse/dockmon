/**
 * Deployments Page
 *
 * Main page for viewing and managing container deployments
 * - List all deployments with filters
 * - Create new deployments
 * - Execute deployments
 * - Monitor progress in real-time
 * - Delete deployments
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, Trash2, Play, Edit, AlertCircle, CheckCircle, XCircle, Loader2, Layers, Bookmark, Search } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient, useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
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
import { useDeployments, useExecuteDeployment, useDeleteDeployment } from './hooks/useDeployments'
import { DeploymentForm } from './components/DeploymentForm'
import { SaveAsTemplateDialog } from './components/SaveAsTemplateDialog'
import { LayerProgressDisplay } from '@/components/shared/LayerProgressDisplay'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import { useContainerModal } from '@/providers/ContainerModalProvider'
import { makeCompositeKeyFrom } from '@/lib/utils/containerKeys'
import { HostDetailsModal } from '@/features/hosts/components/HostDetailsModal'
import type { Deployment, DeploymentStatus, DeploymentFilters } from './types'

export function DeploymentsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { addMessageHandler } = useWebSocketContext()
  const { openModal: openContainerModal } = useContainerModal()

  const [filters, setFilters] = useState<DeploymentFilters>({})
  const [searchQuery, setSearchQuery] = useState('')
  const [showNewDeploymentForm, setShowNewDeploymentForm] = useState(false)
  const [deploymentToEdit, setDeploymentToEdit] = useState<Deployment | null>(null)
  const [deploymentToDelete, setDeploymentToDelete] = useState<Deployment | null>(null)
  const [deploymentToSave, setDeploymentToSave] = useState<Deployment | null>(null)
  const [hostModalOpen, setHostModalOpen] = useState(false)
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null)

  const { data: deploymentsData, isLoading, error} = useDeployments(filters)
  const { data: hosts } = useHosts()
  const { data: containers } = useQuery<any[]>({
    queryKey: ['containers'],
    queryFn: () => apiClient.get('/containers'),
  })
  const executeDeployment = useExecuteDeployment()
  const deleteDeployment = useDeleteDeployment()

  // Client-side search filtering
  const deployments = useMemo(() => {
    if (!deploymentsData) return []
    if (!searchQuery.trim()) return deploymentsData

    const query = searchQuery.toLowerCase()
    return deploymentsData.filter((deployment) => {
      // Search in deployment name, host name, and type
      return (
        deployment.name?.toLowerCase().includes(query) ||
        deployment.host_name?.toLowerCase().includes(query) ||
        deployment.deployment_type?.toLowerCase().includes(query)
      )
    })
  }, [deploymentsData, searchQuery])

  // Status label mapping
  const statusLabels: Record<DeploymentStatus, string> = {
    planning: 'Planning',
    validating: 'Validating',
    pulling_image: 'Pulling Image',
    creating: 'Creating',
    starting: 'Starting',
    running: 'Running',
    failed: 'Failed',
    rolled_back: 'Rolled Back',
  }

  // WebSocket: Listen for real-time deployment progress updates
  const handleDeploymentUpdate = useCallback((message: any) => {
    if (message.type === 'deployment_progress') {
      const { deployment_id, status, progress } = message

      // Update React Query cache directly for instant UI update
      queryClient.setQueryData<Deployment[]>(['deployments', filters], (old) => {
        if (!old) return old

        return old.map((dep) =>
          dep.id === deployment_id
            ? {
                ...dep,
                status: status,
                progress_percent: progress?.overall_percent || dep.progress_percent,
                current_stage: progress?.stage || dep.current_stage,
              }
            : dep
        )
      })
    }
  }, [queryClient, filters])

  useEffect(() => {
    const cleanup = addMessageHandler(handleDeploymentUpdate)
    return cleanup
  }, [addMessageHandler, handleDeploymentUpdate])

  const handleExecute = (deployment: Deployment) => {
    if (deployment.status !== 'planning' && deployment.status !== 'failed' && deployment.status !== 'rolled_back') {
      return
    }
    executeDeployment.mutate(deployment.id)
  }

  const handleEdit = (deployment: Deployment) => {
    // Only allow editing in planning state
    if (deployment.status !== 'planning') {
      return
    }
    setDeploymentToEdit(deployment)
  }

  const handleDelete = (deployment: Deployment) => {
    // Prevent deleting in-progress deployments
    if (deployment.status === 'validating' || deployment.status === 'pulling_image' || deployment.status === 'creating' || deployment.status === 'starting') {
      return
    }

    setDeploymentToDelete(deployment)
  }

  const confirmDelete = () => {
    if (deploymentToDelete) {
      deleteDeployment.mutate(deploymentToDelete.id)
      setDeploymentToDelete(null)
    }
  }

  const handleSaveAsTemplate = (deployment: Deployment) => {
    setDeploymentToSave(deployment)
  }

  const handleOpenHost = (hostId: string) => {
    setSelectedHostId(hostId)
    setHostModalOpen(true)
  }

  const handleOpenContainer = (hostId: string, containerId: string) => {
    // Open container modal with composite key
    const compositeKey = makeCompositeKeyFrom(hostId, containerId)
    openContainerModal(compositeKey, 'info')
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Deployments</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Deploy and manage containers across your Docker hosts
          </p>
        </div>

        <div className="flex gap-3">
          <Button
            variant="outline"
            onClick={() => navigate('/templates')}
            className="gap-2"
            data-testid="manage-templates-button"
          >
            <Layers className="h-4 w-4" />
            Templates
          </Button>

          <Button
            data-testid="new-deployment-button"
            onClick={() => setShowNewDeploymentForm(true)}
            className="gap-2"
          >
            <Plus className="h-4 w-4" />
            New Deployment
          </Button>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="flex gap-4">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search deployments..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
            data-testid="search-deployments"
          />
        </div>

        {/* Status Filter */}
        <Select
          value={filters.status || 'all'}
          onValueChange={(value) => {
            if (value === 'all') {
              const { status, ...rest } = filters
              setFilters(rest)
            } else {
              setFilters({ ...filters, status: value as DeploymentStatus })
            }
          }}
        >
          <SelectTrigger className="w-[200px]" data-testid="filter-status">
            <SelectValue>
              {filters.status ? statusLabels[filters.status] : 'All Statuses'}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="planning">Planning</SelectItem>
            <SelectItem value="validating">Validating</SelectItem>
            <SelectItem value="pulling_image">Pulling Image</SelectItem>
            <SelectItem value="creating">Creating</SelectItem>
            <SelectItem value="starting">Starting</SelectItem>
            <SelectItem value="running">Running</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
            <SelectItem value="rolled_back">Rolled Back</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="flex items-center gap-2 p-4 bg-destructive/10 text-destructive rounded-lg">
          <AlertCircle className="h-5 w-5" />
          <p>Failed to load deployments: {error.message}</p>
        </div>
      )}

      {/* Deployments Table */}
      {!isLoading && !error && (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Host</TableHead>
                <TableHead>Container</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {deployments?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-12 text-muted-foreground">
                    No deployments found. Create your first deployment to get started.
                  </TableCell>
                </TableRow>
              )}

              {deployments?.map((deployment) => (
                <TableRow key={deployment.id} data-testid={`deployment-${deployment.name}`}>
                    {/* Name */}
                  <TableCell className="font-medium">
                    {deployment.name}
                  </TableCell>

                  {/* Host (clickable) */}
                  <TableCell>
                    <button
                      onClick={() => handleOpenHost(deployment.host_id)}
                      className="font-medium text-foreground hover:text-primary transition-colors text-left"
                      title="View host details"
                    >
                      {deployment.host_name || deployment.host_id.slice(0, 8)}
                    </button>
                  </TableCell>

                  {/* Container (clickable if running) */}
                  <TableCell>
                    {deployment.container_ids && deployment.container_ids.length > 0 ? (
                      <div className="flex flex-col gap-1">
                        {deployment.container_ids.map((containerId) => {
                          // Find the container name from the containers list
                          const container = containers?.find(c =>
                            c.id === containerId && c.host_id === deployment.host_id
                          )
                          const displayName = container?.name || containerId

                          return (
                            <button
                              key={containerId}
                              onClick={() => handleOpenContainer(deployment.host_id, containerId)}
                              className="text-foreground hover:text-primary transition-colors text-left"
                              title={container ? `Container: ${container.name}` : 'View container details'}
                            >
                              {displayName}
                            </button>
                          )
                        })}
                      </div>
                    ) : deployment.status === 'planning' ? (
                      <span className="text-xs text-muted-foreground">
                        -
                      </span>
                    ) : deployment.status === 'running' ? (
                      <span
                        className="text-xs text-muted-foreground italic"
                        title="Container tracking not available for deployments created before v2.1. Create a new deployment to see container links."
                      >
                        Legacy deployment
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        -
                      </span>
                    )}
                  </TableCell>

                  {/* Type */}
                  <TableCell className="capitalize">{deployment.deployment_type}</TableCell>

                  {/* Status */}
                  <TableCell>
                    <StatusBadge status={deployment.status} />
                  </TableCell>

                  {/* Progress */}
                  <TableCell>
                    {(deployment.status === 'validating' || deployment.status === 'pulling_image' || deployment.status === 'creating' || deployment.status === 'starting') && (
                      <div className="min-w-[200px]">
                        <LayerProgressDisplay
                          hostId={deployment.host_id}
                          entityId={deployment.id}
                          eventType="deployment_layer_progress"
                          simpleProgressEventType="deployment_progress"
                          initialProgress={deployment.progress_percent}
                          initialMessage={deployment.current_stage || 'Processing...'}
                        />
                      </div>
                    )}
                    {deployment.status === 'running' && (
                      <span className="text-xs text-green-600" data-testid="deployment-running">
                        100%
                      </span>
                    )}
                    {deployment.status === 'failed' && deployment.error_message && (
                      <p className="text-xs text-destructive" data-testid="deployment-error">
                        {deployment.error_message.slice(0, 50)}...
                      </p>
                    )}
                    {deployment.status === 'rolled_back' && (
                      <span className="text-xs text-yellow-600" data-testid="deployment-rolled-back">
                        Rolled back
                      </span>
                    )}
                  </TableCell>

                  {/* Created */}
                  <TableCell className="text-sm text-muted-foreground">
                    {new Date(deployment.created_at).toLocaleString()}
                  </TableCell>

                  {/* Actions */}
                  <TableCell className="text-right space-x-2">
                    {deployment.status === 'planning' && (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEdit(deployment)}
                          data-testid={`edit-deployment-${deployment.name}`}
                          title="Edit"
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleExecute(deployment)}
                          disabled={executeDeployment.isPending}
                          data-testid={`execute-deployment-${deployment.name}`}
                        >
                          <Play className="h-4 w-4 mr-1" />
                          Execute
                        </Button>
                      </>
                    )}
                    {(deployment.status === 'failed' || deployment.status === 'rolled_back') && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleExecute(deployment)}
                        disabled={executeDeployment.isPending}
                        data-testid={`execute-deployment-${deployment.name}`}
                      >
                        <Play className="h-4 w-4 mr-1" />
                        Execute
                      </Button>
                    )}

                    {deployment.status === 'running' && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleSaveAsTemplate(deployment)}
                        data-testid="save-as-template"
                        title="Save as New Template"
                      >
                        <Bookmark className="h-4 w-4 mr-1" />
                        Save as New Template
                      </Button>
                    )}

                    {(deployment.status === 'running' || deployment.status === 'failed' || deployment.status === 'rolled_back' || deployment.status === 'planning') && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(deployment)}
                        disabled={deleteDeployment.isPending}
                        title="Delete"
                        data-testid={`delete-deployment-${deployment.name}`}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Deployment Form Modal (Create) */}
      <DeploymentForm
        isOpen={showNewDeploymentForm}
        onClose={() => setShowNewDeploymentForm(false)}
        hosts={(hosts || []).map(h => ({ id: h.id, name: h.name || h.id }))}
      />

      {/* Deployment Form Modal (Edit) */}
      {deploymentToEdit && (
        <DeploymentForm
          isOpen={true}
          onClose={() => setDeploymentToEdit(null)}
          deployment={deploymentToEdit}
          hosts={(hosts || []).map(h => ({ id: h.id, name: h.name || h.id }))}
        />
      )}

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!deploymentToDelete} onOpenChange={(open) => !open && setDeploymentToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Deployment</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete deployment "<strong>{deploymentToDelete?.name}</strong>"?
              This action cannot be undone.
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

      {/* Save as Template Dialog */}
      <SaveAsTemplateDialog
        deployment={deploymentToSave}
        isOpen={!!deploymentToSave}
        onClose={() => setDeploymentToSave(null)}
      />

      {/* Host Details Modal */}
      <HostDetailsModal
        hostId={selectedHostId}
        host={hosts?.find(h => h.id === selectedHostId)}
        open={hostModalOpen}
        onClose={() => {
          setHostModalOpen(false)
          setSelectedHostId(null)
        }}
      />
    </div>
  )
}

/**
 * Status badge with appropriate styling
 */
function StatusBadge({ status }: { status: DeploymentStatus }) {
  const variants: Record<DeploymentStatus, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; icon: React.ReactNode }> = {
    planning: {
      variant: 'secondary',
      icon: <AlertCircle className="h-3 w-3" />,
    },
    validating: {
      variant: 'outline',
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
    },
    pulling_image: {
      variant: 'outline',
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
    },
    creating: {
      variant: 'outline',
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
    },
    starting: {
      variant: 'outline',
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
    },
    running: {
      variant: 'default',
      icon: <CheckCircle className="h-3 w-3" />,
    },
    failed: {
      variant: 'destructive',
      icon: <XCircle className="h-3 w-3" />,
    },
    rolled_back: {
      variant: 'secondary',
      icon: <XCircle className="h-3 w-3" />,
    },
  }

  const { variant, icon } = variants[status]

  return (
    <Badge variant={variant} className="gap-1">
      {icon}
      {status.replace(/_/g, ' ')}
    </Badge>
  )
}
