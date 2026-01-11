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
import { Plus, Trash2, Play, Edit, AlertCircle, CheckCircle, XCircle, Loader2, Layers, Search, Download, RefreshCw, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
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
import { useDeployments, useExecuteDeployment, useDeleteDeployment, useRedeployDeployment } from './hooks/useDeployments'
import { DeploymentForm } from './components/DeploymentForm'
import { ImportStackModal } from './components/ImportStackModal'
import { LayerProgressDisplay } from '@/components/shared/LayerProgressDisplay'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import { useContainerModal } from '@/providers/ContainerModalProvider'
import { makeCompositeKeyFrom } from '@/lib/utils/containerKeys'
import { HostDetailsModal } from '@/features/hosts/components/HostDetailsModal'
import type { Container } from '@/features/containers/types'
import type { WebSocketMessage } from '@/lib/websocket/useWebSocket'
import type { Deployment, DeploymentStatus, DeploymentFilters } from './types'

export function DeploymentsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { addMessageHandler } = useWebSocketContext()
  const { openModal: openContainerModal } = useContainerModal()

  const [filters, setFilters] = useState<DeploymentFilters>({})
  const [searchQuery, setSearchQuery] = useState('')
  type SortColumn = 'name' | 'host_name' | 'status' | 'created_at'
  const [sortColumn, setSortColumn] = useState<SortColumn>(() => {
    const saved = localStorage.getItem('deployments_sort_column')
    const validColumns: SortColumn[] = ['name', 'host_name', 'status', 'created_at']
    return validColumns.includes(saved as SortColumn) ? (saved as SortColumn) : 'created_at'
  })
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>(() => {
    const saved = localStorage.getItem('deployments_sort_direction')
    return saved === 'asc' || saved === 'desc' ? saved : 'desc'
  })
  const [showNewDeploymentForm, setShowNewDeploymentForm] = useState(false)
  const [showImportModal, setShowImportModal] = useState(false)
  const [deploymentToEdit, setDeploymentToEdit] = useState<Deployment | null>(null)
  const [deploymentToDelete, setDeploymentToDelete] = useState<Deployment | null>(null)
  const [deploymentToRedeploy, setDeploymentToRedeploy] = useState<Deployment | null>(null)
  const [hostModalOpen, setHostModalOpen] = useState(false)
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null)

  const { data: deploymentsData, isLoading, error} = useDeployments(filters)
  const { data: hosts } = useHosts()
  const { data: containers } = useQuery<Container[]>({
    queryKey: ['containers'],
    queryFn: () => apiClient.get('/containers'),
  })
  const executeDeployment = useExecuteDeployment()
  const redeployDeployment = useRedeployDeployment()
  const deleteDeployment = useDeleteDeployment()

  // Client-side search filtering and sorting
  const deployments = useMemo(() => {
    if (!deploymentsData) return []

    // Filter by search query
    let filtered = deploymentsData
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      filtered = deploymentsData.filter((deployment) => {
        return (
          deployment.stack_name?.toLowerCase().includes(query) ||
          deployment.host_name?.toLowerCase().includes(query) ||
          deployment.status?.toLowerCase().includes(query)
        )
      })
    }

    // Sort
    const sorted = [...filtered].sort((a, b) => {
      let aVal: string | number = ''
      let bVal: string | number = ''

      switch (sortColumn) {
        case 'name':
          aVal = a.stack_name?.toLowerCase() || ''
          bVal = b.stack_name?.toLowerCase() || ''
          break
        case 'host_name':
          aVal = a.host_name?.toLowerCase() || ''
          bVal = b.host_name?.toLowerCase() || ''
          break
        case 'status':
          aVal = a.status?.toLowerCase() || ''
          bVal = b.status?.toLowerCase() || ''
          break
        case 'created_at':
          aVal = new Date(a.created_at).getTime()
          bVal = new Date(b.created_at).getTime()
          break
      }

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1
      return 0
    })

    return sorted
  }, [deploymentsData, searchQuery, sortColumn, sortDirection])

  // Toggle sort for a column
  const handleSort = (column: SortColumn) => {
    if (sortColumn === column) {
      const newDirection = sortDirection === 'asc' ? 'desc' : 'asc'
      setSortDirection(newDirection)
      localStorage.setItem('deployments_sort_direction', newDirection)
    } else {
      setSortColumn(column)
      setSortDirection('asc')
      localStorage.setItem('deployments_sort_column', column)
      localStorage.setItem('deployments_sort_direction', 'asc')
    }
  }

  // Sort icon helper
  const SortIcon = ({ column }: { column: SortColumn }) => {
    if (sortColumn !== column) {
      return <ArrowUpDown className="ml-2 h-4 w-4 text-muted-foreground" />
    }
    return sortDirection === 'asc'
      ? <ArrowUp className="ml-2 h-4 w-4 text-primary" />
      : <ArrowDown className="ml-2 h-4 w-4 text-primary" />
  }

  // Status label mapping (user-facing labels for display)
  const statusLabels: Record<DeploymentStatus, string> = {
    planning: 'Planning',
    validating: 'Validating',
    pulling_image: 'Pulling Image',
    creating: 'Creating',
    starting: 'Starting',
    running: 'Deployed',
    partial: 'Partial',
    failed: 'Failed',
    rolled_back: 'Rolled Back',
    stopped: 'Stopped',
  }

  // WebSocket: Listen for real-time deployment updates
  const handleDeploymentUpdate = useCallback((message: WebSocketMessage) => {
    // Handle all deployment event types
    const deploymentEventTypes = [
      'deployment_created',
      'deployment_progress',
      'deployment_completed',
      'deployment_failed',
      'deployment_rolled_back',
    ]

    if (deploymentEventTypes.includes(message.type)) {
      // Extract deployment data - structure varies by message type
      const msg = message as { type: string; deployment_id?: string; status?: string; progress?: { overall_percent?: number; stage?: string } }
      const { deployment_id, status, progress } = msg

      // Update ALL deployment queries (all filter combinations) to avoid race condition
      // if filters change while message is being processed
      // Use setQueriesData (plural) instead of setQueryData to update all matching queries
      queryClient.setQueriesData(
        { queryKey: ['deployments'] },
        (old: Deployment[] | undefined) => {
          if (!Array.isArray(old)) return old

          return old.map((dep: Deployment) =>
            dep.id === deployment_id
              ? {
                  ...dep,
                  status: status ?? dep.status,
                  progress_percent: progress?.overall_percent ?? dep.progress_percent,
                  current_stage: progress?.stage ?? dep.current_stage,
                }
              : dep
          )
        }
      )

      // When deployment reaches a final state, refetch to get container_ids and other final data
      // Use prefix matching (['deployments']) to ensure all deployment queries are invalidated
      // regardless of filter state changes
      if (status === 'running' || status === 'partial' || status === 'failed' || status === 'rolled_back') {
        queryClient.invalidateQueries({ queryKey: ['deployments'] })
      }
    }
  }, [queryClient])

  useEffect(() => {
    const cleanup = addMessageHandler(handleDeploymentUpdate)
    return cleanup
  }, [addMessageHandler, handleDeploymentUpdate])

  const handleExecute = (deployment: Deployment) => {
    if (deployment.status !== 'planning' && deployment.status !== 'failed' && deployment.status !== 'rolled_back' && deployment.status !== 'partial') {
      return
    }
    executeDeployment.mutate(deployment.id)
  }

  const handleEdit = (deployment: Deployment) => {
    // Allow editing in planning, failed, rolled_back, partial, and running states
    if (deployment.status !== 'planning' && deployment.status !== 'failed' && deployment.status !== 'rolled_back' && deployment.status !== 'partial' && deployment.status !== 'running') {
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

  const handleRedeploy = (deployment: Deployment) => {
    // Only allow redeploy for running or partial deployments
    if (deployment.status !== 'running' && deployment.status !== 'partial') {
      return
    }
    setDeploymentToRedeploy(deployment)
  }

  const confirmRedeploy = () => {
    if (deploymentToRedeploy) {
      redeployDeployment.mutate(deploymentToRedeploy.id)
      setDeploymentToRedeploy(null)
    }
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
    <div className="p-3 sm:p-4 md:p-6 pt-16 md:pt-6 space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold">Deployments</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Deploy and manage containers across your Docker hosts
          </p>
        </div>

        <div className="flex gap-2 sm:gap-3 flex-wrap">
          <Button
            variant="outline"
            onClick={() => navigate('/stacks')}
            className="gap-2"
            data-testid="manage-stacks-button"
          >
            <Layers className="h-4 w-4" />
            Stacks
          </Button>

          <Button
            variant="outline"
            onClick={() => setShowImportModal(true)}
            className="gap-2"
            data-testid="import-stack-button"
          >
            <Download className="h-4 w-4" />
            Import Stack
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
            <SelectItem value="running">Deployed</SelectItem>
            <SelectItem value="stopped">Stopped</SelectItem>
            <SelectItem value="partial">Partial</SelectItem>
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
                <TableHead>
                  <Button variant="ghost" onClick={() => handleSort('name')} className="h-8 px-2 hover:bg-surface-2">
                    Name
                    <SortIcon column="name" />
                  </Button>
                </TableHead>
                <TableHead>
                  <Button variant="ghost" onClick={() => handleSort('host_name')} className="h-8 px-2 hover:bg-surface-2">
                    Host
                    <SortIcon column="host_name" />
                  </Button>
                </TableHead>
                <TableHead>Container</TableHead>
                <TableHead>
                  <Button variant="ghost" onClick={() => handleSort('status')} className="h-8 px-2 hover:bg-surface-2">
                    Status
                    <SortIcon column="status" />
                  </Button>
                </TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>
                  <Button variant="ghost" onClick={() => handleSort('created_at')} className="h-8 px-2 hover:bg-surface-2">
                    Created
                    <SortIcon column="created_at" />
                  </Button>
                </TableHead>
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
                <TableRow key={deployment.id} data-testid={`deployment-${deployment.stack_name}`}>
                    {/* Name */}
                  <TableCell className="font-medium">
                    {deployment.stack_name}
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
                          disableAutoCollapse={true}
                        />
                      </div>
                    )}
                    {deployment.status === 'running' && (
                      <span className="text-xs text-green-600" data-testid="deployment-running">
                        100%
                      </span>
                    )}
                    {deployment.status === 'partial' && deployment.error_message && (
                      <div className="text-sm text-amber-600 font-medium max-w-sm" data-testid="deployment-partial">
                        {deployment.error_message}
                      </div>
                    )}
                    {deployment.status === 'partial' && !deployment.error_message && (
                      <span className="text-xs text-amber-600" data-testid="deployment-partial">
                        Some services failed
                      </span>
                    )}
                    {deployment.status === 'failed' && deployment.error_message && (
                      <div className="text-sm text-destructive font-medium max-w-sm" data-testid="deployment-error">
                        {deployment.error_message}
                      </div>
                    )}
                    {deployment.status === 'rolled_back' && deployment.error_message && (
                      <div className="text-sm text-yellow-600 font-medium max-w-sm" data-testid="deployment-error">
                        {deployment.error_message}
                      </div>
                    )}
                    {deployment.status === 'rolled_back' && !deployment.error_message && (
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
                          data-testid={`edit-deployment-${deployment.stack_name}`}
                          title="Edit"
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleExecute(deployment)}
                          disabled={executeDeployment.isPending}
                          data-testid={`execute-deployment-${deployment.stack_name}`}
                        >
                          <Play className="h-4 w-4 mr-1" />
                          Execute
                        </Button>
                      </>
                    )}
                    {(deployment.status === 'failed' || deployment.status === 'rolled_back') && (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEdit(deployment)}
                          data-testid={`edit-deployment-${deployment.stack_name}`}
                          title="Edit and retry"
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleExecute(deployment)}
                          disabled={executeDeployment.isPending}
                          data-testid={`execute-deployment-${deployment.stack_name}`}
                        >
                          <Play className="h-4 w-4 mr-1" />
                          Retry
                        </Button>
                      </>
                    )}

                    {(deployment.status === 'running' || deployment.status === 'partial') && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleEdit(deployment)}
                        data-testid={`edit-deployment-${deployment.stack_name}`}
                        title="Edit stack"
                      >
                        <Edit className="h-4 w-4" />
                      </Button>
                    )}

                    {(deployment.status === 'running' || deployment.status === 'partial') && (
                      <>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleRedeploy(deployment)}
                          disabled={redeployDeployment.isPending}
                          data-testid={`redeploy-deployment-${deployment.stack_name}`}
                          title="Redeploy - pull latest images and recreate containers"
                        >
                          <RefreshCw className="h-4 w-4 mr-1" />
                          Redeploy
                        </Button>
                      </>
                    )}

                    {(deployment.status === 'running' || deployment.status === 'partial' || deployment.status === 'failed' || deployment.status === 'rolled_back' || deployment.status === 'planning') && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(deployment)}
                        disabled={deleteDeployment.isPending}
                        title="Delete"
                        data-testid={`delete-deployment-${deployment.stack_name}`}
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
              Are you sure you want to delete deployment "<strong>{deploymentToDelete?.stack_name}</strong>"?
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

      {/* Redeploy Confirmation Dialog */}
      <AlertDialog open={!!deploymentToRedeploy} onOpenChange={(open) => !open && setDeploymentToRedeploy(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Redeploy Stack</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to redeploy "<strong>{deploymentToRedeploy?.stack_name}</strong>"?
              <br /><br />
              This will:
              <ul className="list-disc list-inside mt-2 space-y-1">
                <li>Pull the latest images for all services</li>
                <li>Recreate all containers with the new images</li>
                <li>Brief service interruption during container recreation</li>
              </ul>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmRedeploy}>
              Redeploy
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Import Stack Modal */}
      <ImportStackModal
        isOpen={showImportModal}
        onClose={() => setShowImportModal(false)}
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
  const variants: Record<DeploymentStatus, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; icon: React.ReactNode; label: string }> = {
    planning: {
      variant: 'secondary',
      icon: <AlertCircle className="h-3 w-3" />,
      label: 'Planning',
    },
    validating: {
      variant: 'outline',
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
      label: 'Validating',
    },
    pulling_image: {
      variant: 'outline',
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
      label: 'Pulling Image',
    },
    creating: {
      variant: 'outline',
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
      label: 'Creating',
    },
    starting: {
      variant: 'outline',
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
      label: 'Starting',
    },
    running: {
      variant: 'default',
      icon: <CheckCircle className="h-3 w-3" />,
      label: 'Deployed',
    },
    partial: {
      variant: 'outline',
      icon: <AlertCircle className="h-3 w-3 text-amber-500" />,
      label: 'Partial',
    },
    failed: {
      variant: 'destructive',
      icon: <XCircle className="h-3 w-3" />,
      label: 'Failed',
    },
    rolled_back: {
      variant: 'secondary',
      icon: <XCircle className="h-3 w-3" />,
      label: 'Rolled Back',
    },
    stopped: {
      variant: 'secondary',
      icon: <AlertCircle className="h-3 w-3" />,
      label: 'Stopped',
    },
  }

  // Fallback for unknown statuses (future-proofing)
  const { variant, icon, label } = variants[status] ?? {
    variant: 'outline' as const,
    icon: <AlertCircle className="h-3 w-3" />,
    label: status,
  }

  return (
    <Badge variant={variant} className="gap-1">
      {icon}
      {label}
    </Badge>
  )
}
