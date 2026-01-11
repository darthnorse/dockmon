/**
 * Stacks Management Page (v2.2.7+)
 *
 * Browse, create, edit, and delete stacks (filesystem-based compose configurations).
 * - List stacks with deployment counts
 * - Create new stacks with compose YAML and optional .env
 * - Edit existing stacks (including rename)
 * - Copy stacks
 * - Delete stacks (only if no deployments reference them)
 */

import { useState } from 'react'
import { Plus, Edit, Trash2, Copy, AlertCircle, ArrowLeft, FileText } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'
import { useStacks, useDeleteStack, useCopyStack } from './hooks/useStacks'
import { StackForm } from './components/StackForm'
import { validateStackName, MAX_STACK_NAME_LENGTH } from './types'
import type { StackListItem } from './types'

export function StacksPage() {
  const navigate = useNavigate()
  const [showStackForm, setShowStackForm] = useState(false)
  const [editingStackName, setEditingStackName] = useState<string | null>(null)
  const [stackToDelete, setStackToDelete] = useState<StackListItem | null>(null)
  const [stackToCopy, setStackToCopy] = useState<StackListItem | null>(null)
  const [copyDestName, setCopyDestName] = useState('')

  const { data: stacks, isLoading, error } = useStacks()
  const deleteStack = useDeleteStack()
  const copyStack = useCopyStack()

  const handleEdit = (stack: StackListItem) => {
    setEditingStackName(stack.name)
    setShowStackForm(true)
  }

  const handleDelete = (stack: StackListItem) => {
    if (stack.deployment_count > 0) {
      return // Can't delete stacks with active deployments
    }
    setStackToDelete(stack)
  }

  const confirmDelete = () => {
    if (stackToDelete) {
      deleteStack.mutate(stackToDelete.name)
      setStackToDelete(null)
    }
  }

  const handleCopy = (stack: StackListItem) => {
    setStackToCopy(stack)
    setCopyDestName(`${stack.name}-copy`)
  }

  const confirmCopy = () => {
    const trimmedName = copyDestName.trim()
    if (!stackToCopy || !trimmedName) {
      return
    }

    // Validate name format using shared utility
    const validationError = validateStackName(trimmedName)
    if (validationError) {
      toast.error(validationError)
      return
    }

    copyStack.mutate(
      { name: stackToCopy.name, dest_name: trimmedName },
      {
        onSuccess: () => {
          setStackToCopy(null)
          setCopyDestName('')
        },
      }
    )
  }

  const handleCloseForm = () => {
    setShowStackForm(false)
    setEditingStackName(null)
  }

  return (
    <div className="p-6 space-y-6">
      {/* Back to Deployments */}
      <Button
        variant="ghost"
        onClick={() => navigate('/deployments')}
        className="gap-2 -ml-2"
        data-testid="back-to-deployments"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Deployments
      </Button>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Stacks</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Docker Compose configurations stored on filesystem
          </p>
        </div>

        <Button
          data-testid="new-stack-button"
          onClick={() => setShowStackForm(true)}
          className="gap-2"
        >
          <Plus className="h-4 w-4" />
          New Stack
        </Button>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <p className="text-muted-foreground">Loading stacks...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="flex items-center gap-2 p-4 bg-destructive/10 text-destructive rounded-lg">
          <AlertCircle className="h-5 w-5" />
          <p>Failed to load stacks: {error.message}</p>
        </div>
      )}

      {/* Stacks Table */}
      {!isLoading && !error && (
        <div className="rounded-lg border" data-testid="stack-list">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Deployments</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(!stacks || stacks.length === 0) && (
                <TableRow>
                  <TableCell colSpan={3} className="text-center py-12 text-muted-foreground">
                    <div className="flex flex-col items-center gap-2">
                      <FileText className="h-8 w-8 opacity-50" />
                      <p>No stacks found. Create your first stack to get started.</p>
                    </div>
                  </TableCell>
                </TableRow>
              )}

              {stacks?.map((stack) => (
                <TableRow key={stack.name} data-testid={`stack-${stack.name}`}>
                  {/* Name */}
                  <TableCell className="font-medium font-mono">{stack.name}</TableCell>

                  {/* Deployment Count */}
                  <TableCell>
                    {stack.deployment_count > 0 ? (
                      <Badge variant="secondary">
                        {stack.deployment_count} deployment{stack.deployment_count !== 1 ? 's' : ''}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground text-sm">No deployments</span>
                    )}
                  </TableCell>

                  {/* Actions */}
                  <TableCell className="text-right space-x-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleEdit(stack)}
                      title="Edit stack"
                      data-testid={`edit-stack-${stack.name}`}
                    >
                      <Edit className="h-4 w-4" />
                    </Button>

                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleCopy(stack)}
                      title="Copy"
                      data-testid={`copy-stack-${stack.name}`}
                    >
                      <Copy className="h-4 w-4" />
                    </Button>

                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(stack)}
                      disabled={deleteStack.isPending || stack.deployment_count > 0}
                      title={stack.deployment_count > 0 ? 'Cannot delete: has active deployments' : 'Delete'}
                      data-testid={`delete-stack-${stack.name}`}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Stack Form Modal */}
      <StackForm
        isOpen={showStackForm}
        onClose={handleCloseForm}
        stackName={editingStackName}
      />

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!stackToDelete} onOpenChange={(open) => !open && setStackToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Stack</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete stack "<strong>{stackToDelete?.name}</strong>"?
              This will remove the compose.yaml and .env files from the filesystem.
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

      {/* Copy Dialog */}
      <Dialog open={!!stackToCopy} onOpenChange={(open) => !open && setStackToCopy(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Copy Stack</DialogTitle>
            <DialogDescription>
              Create a copy of "<strong>{stackToCopy?.name}</strong>" with a new name.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="copy-dest-name">New Stack Name</Label>
              <Input
                id="copy-dest-name"
                value={copyDestName}
                onChange={(e) => setCopyDestName(e.target.value)}
                placeholder="my-stack-copy"
                className="font-mono"
                maxLength={MAX_STACK_NAME_LENGTH}
              />
              <p className="text-xs text-muted-foreground">
                Lowercase letters, numbers, hyphens, and underscores only
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setStackToCopy(null)}>
              Cancel
            </Button>
            <Button
              onClick={confirmCopy}
              disabled={!copyDestName.trim() || copyStack.isPending}
            >
              {copyStack.isPending ? 'Copying...' : 'Copy Stack'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  )
}
