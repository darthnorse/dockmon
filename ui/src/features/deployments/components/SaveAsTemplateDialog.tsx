/**
 * Save as Template Dialog
 *
 * Allows users to save a successful deployment as a reusable template.
 * Captures template name, category, and description.
 */

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useSaveAsTemplate } from '../hooks/useDeployments'
import type { Deployment } from '../types'

interface SaveAsTemplateDialogProps {
  deployment: Deployment | null
  isOpen: boolean
  onClose: () => void
}

export function SaveAsTemplateDialog({
  deployment,
  isOpen,
  onClose,
}: SaveAsTemplateDialogProps) {
  const [name, setName] = useState('')
  const [category, setCategory] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)

  const saveAsTemplate = useSaveAsTemplate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!deployment) return

    if (!name.trim()) {
      setError('Template name is required')
      return
    }

    setError(null)

    try {
      await saveAsTemplate.mutateAsync({
        deploymentId: deployment.id,
        name: name.trim(),
        category: category.trim() || null,
        description: description.trim() || null,
      })

      // Reset form and close on success
      setName('')
      setCategory('')
      setDescription('')
      setError(null)
      onClose()
    } catch (err: any) {
      // Extract error message from response
      const errorMessage = err?.message || 'Failed to save template'

      // Check for duplicate name error (409 conflict)
      if (errorMessage.includes('already exists')) {
        setError('A template with this name already exists. Please choose a different name.')
      } else {
        setError(errorMessage)
      }
    }
  }

  const handleCancel = () => {
    // Reset form state
    setName('')
    setCategory('')
    setDescription('')
    setError(null)
    onClose()
  }

  // Reset form when dialog closes
  const handleOpenChange = (open: boolean) => {
    if (!open) {
      handleCancel()
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent data-testid="save-as-template-dialog">
        <DialogHeader>
          <DialogTitle>Save as Template</DialogTitle>
          <DialogDescription>
            {deployment
              ? `Create a reusable template from "${deployment.name}"`
              : 'Create a reusable template'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
          <div className="space-y-4 py-4">
            {/* Template Name (required) */}
            <div>
              <Label htmlFor="template-name">
                Template Name <span className="text-destructive">*</span>
              </Label>
              <Input
                id="template-name"
                name="name"
                data-testid="template-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., nginx-web-server"
                className={error && error.includes('name') ? 'border-destructive' : ''}
              />
            </div>

            {/* Category (optional) */}
            <div>
              <Label htmlFor="template-category">Category</Label>
              <Input
                id="template-category"
                name="category"
                data-testid="template-category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g., web-servers, databases"
              />
            </div>

            {/* Description (optional) */}
            <div>
              <Label htmlFor="template-description">Description</Label>
              <Textarea
                id="template-description"
                name="description"
                data-testid="template-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe what this template deploys..."
                rows={3}
              />
              <p className="text-xs text-muted-foreground mt-1">
                If not provided, a default description will be generated.
              </p>
            </div>

            {/* Error Message */}
            {error && (
              <div className="text-sm text-destructive" role="alert">
                {error}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={handleCancel}
              disabled={saveAsTemplate.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="save-template-button"
              disabled={saveAsTemplate.isPending || !name.trim()}
            >
              {saveAsTemplate.isPending ? 'Saving...' : 'Save Template'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
