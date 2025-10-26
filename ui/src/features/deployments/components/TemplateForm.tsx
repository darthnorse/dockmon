/**
 * Template Form Component
 *
 * Create or edit deployment templates
 * - Template metadata (name, category, description)
 * - Template definition (JSON editor)
 * - Variable definitions
 * - Form validation
 */

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCreateTemplate, useUpdateTemplate } from '../hooks/useTemplates'
import type { DeploymentTemplate, DeploymentDefinition } from '../types'

interface TemplateFormProps {
  isOpen: boolean
  onClose: () => void
  template?: DeploymentTemplate | null  // If provided, edit mode
}

export function TemplateForm({ isOpen, onClose, template }: TemplateFormProps) {
  const createTemplate = useCreateTemplate()
  const updateTemplate = useUpdateTemplate()

  const isEditMode = !!template

  // Form state
  const [name, setName] = useState('')
  const [category, setCategory] = useState('')
  const [description, setDescription] = useState('')
  const [deploymentType, setDeploymentType] = useState<'container' | 'stack'>('container')
  const [definition, setDefinition] = useState('')

  // Validation errors
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Load template data in edit mode
  useEffect(() => {
    if (template && isOpen) {
      setName(template.name)
      setCategory(template.category || '')
      setDescription(template.description || '')
      setDeploymentType(template.deployment_type as 'container' | 'stack')
      setDefinition(JSON.stringify(template.template_definition, null, 2))
    }
  }, [template, isOpen])

  // Reset form when closed
  useEffect(() => {
    if (!isOpen) {
      setName('')
      setCategory('')
      setDescription('')
      setDeploymentType('container')
      setDefinition('')
      setErrors({})
    }
  }, [isOpen])

  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {}

    if (!name.trim()) {
      newErrors.name = 'Template name is required'
    }

    if (!definition.trim()) {
      newErrors.definition = 'Template definition is required'
    } else {
      // Validate JSON
      try {
        JSON.parse(definition)
      } catch (e) {
        newErrors.definition = 'Invalid JSON format'
      }
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
      const parsedDefinition = JSON.parse(definition) as DeploymentDefinition

      if (isEditMode && template) {
        // Update existing template
        await updateTemplate.mutateAsync({
          id: template.id,
          name: name.trim(),
          category: category.trim() || null,
          description: description.trim() || null,
          template_definition: parsedDefinition,
          variables: null,  // TODO: Add variable editor
        })
      } else {
        // Create new template
        await createTemplate.mutateAsync({
          name: name.trim(),
          deployment_type: deploymentType,
          template_definition: parsedDefinition,
          category: category.trim() || null,
          description: description.trim() || null,
          variables: null,  // TODO: Add variable editor
        })
      }

      onClose()
    } catch (error) {
      // Error handling is done in hooks (toast notifications)
      console.error('Template save failed:', error)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="template-form">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? 'Edit Template' : 'Create Template'}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? 'Update the template configuration'
              : 'Create a reusable deployment template'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div>
            <Label htmlFor="name">Template Name *</Label>
            <Input
              id="name"
              name="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., nginx-web-server"
              className={errors.name ? 'border-destructive' : ''}
            />
            {errors.name && (
              <p className="text-sm text-destructive mt-1">{errors.name}</p>
            )}
          </div>

          {/* Category */}
          <div>
            <Label htmlFor="category">Category</Label>
            <Input
              id="category"
              name="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="e.g., web-servers, databases"
            />
          </div>

          {/* Description */}
          <div>
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              name="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what this template deploys..."
              rows={3}
            />
          </div>

          {/* Deployment Type */}
          {!isEditMode && (
            <div>
              <Label htmlFor="deployment-type">Deployment Type *</Label>
              <Select
                value={deploymentType}
                onValueChange={(value) => setDeploymentType(value as 'container' | 'stack')}
              >
                <SelectTrigger id="deployment-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="container">Container</SelectItem>
                  <SelectItem value="stack">Stack (Compose)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Template Definition (JSON) */}
          <div>
            <Label htmlFor="definition">Template Definition (JSON) *</Label>
            <Textarea
              id="definition"
              name="definition"
              value={definition}
              onChange={(e) => setDefinition(e.target.value)}
              placeholder='{"image": "nginx:latest", "ports": ["80:80"]}'
              rows={12}
              className={`font-mono text-sm ${errors.definition ? 'border-destructive' : ''}`}
              data-testid="template-definition"
            />
            {errors.definition && (
              <p className="text-sm text-destructive mt-1">{errors.definition}</p>
            )}
            <p className="text-xs text-muted-foreground mt-1">
              Use ${`{VARIABLE_NAME}`} for variable placeholders
            </p>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={createTemplate.isPending || updateTemplate.isPending}
            >
              {isEditMode ? 'Save Changes' : 'Create Template'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
