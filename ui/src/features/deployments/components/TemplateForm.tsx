/**
 * Template Form Component
 *
 * Create or edit deployment templates
 * - Template metadata (name, category, description)
 * - Template definition (JSON editor)
 * - Variable definitions
 * - Form validation
 */

import { useState, useEffect, useRef } from 'react'
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
import { ConfigurationEditor, ConfigurationEditorHandle } from './ConfigurationEditor'
import { VariableDefinitionEditor } from './VariableDefinitionEditor'
import type { DeploymentTemplate, DeploymentDefinition, TemplateVariableConfig } from '../types'

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
  const [variables, setVariables] = useState<Record<string, TemplateVariableConfig>>({})

  // Validation errors
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Ref to ConfigurationEditor for validation
  const configEditorRef = useRef<ConfigurationEditorHandle>(null)

  // Load template data in edit mode
  useEffect(() => {
    if (template && isOpen) {
      setName(template.name)
      setCategory(template.category || '')
      setDescription(template.description || '')
      setDeploymentType(template.deployment_type as 'container' | 'stack')

      // Format the definition for display
      let formatted: string
      if (template.deployment_type === 'stack' && 'compose_yaml' in template.template_definition && template.template_definition.compose_yaml) {
        // For stacks: show the YAML directly (not wrapped in JSON)
        // This makes it much easier to read and edit
        formatted = template.template_definition.compose_yaml
      } else {
        // For containers: show as formatted JSON
        formatted = JSON.stringify(template.template_definition, null, 2)
      }

      setDefinition(formatted)

      // Load variables
      setVariables(template.variables || {})
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
      setVariables({})
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
    } else if (deploymentType === 'container') {
      // For containers: validate JSON format
      try {
        JSON.parse(definition)
      } catch (e) {
        newErrors.definition = 'Invalid JSON format'
      }
    }
    // For stacks: no validation needed - raw YAML is accepted

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!validateForm()) {
      return
    }

    // Validate YAML/JSON configuration before saving
    if (configEditorRef.current && definition.trim()) {
      const validation = configEditorRef.current.validate()
      if (!validation.valid) {
        setErrors({
          ...errors,
          definition: validation.error || 'Invalid format. Please fix errors before saving.',
        })
        return
      }
    }

    try {
      // Parse the definition based on deployment type
      let parsedDefinition: DeploymentDefinition

      if (deploymentType === 'stack') {
        // For stacks: the definition field contains raw YAML, wrap it
        parsedDefinition = { compose_yaml: definition }
      } else {
        // For containers: the definition field contains JSON, parse it
        parsedDefinition = JSON.parse(definition) as DeploymentDefinition
      }

      const variablesToSend = Object.keys(variables).length > 0 ? variables : null

      if (isEditMode && template) {
        // Update existing template
        await updateTemplate.mutateAsync({
          id: template.id,
          name: name.trim(),
          category: category.trim() || null,
          description: description.trim() || null,
          template_definition: parsedDefinition,
          variables: variablesToSend,
        })
      } else {
        // Create new template
        await createTemplate.mutateAsync({
          name: name.trim(),
          deployment_type: deploymentType,
          template_definition: parsedDefinition,
          category: category.trim() || null,
          description: description.trim() || null,
          variables: variablesToSend,
        })
      }

      onClose()
    } catch (error: any) {
      // Check for duplicate name error
      if (error.message && error.message.includes('already exists')) {
        setErrors({
          ...errors,
          name: 'A template with this name already exists. Please choose a different name.',
        })
        return // Keep form open so user can fix the error
      }

      // Other errors - log and let hooks handle toast
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

          {/* Template Definition */}
          <div>
            <Label htmlFor="definition">
              {deploymentType === 'stack' ? 'Compose YAML *' : 'Template Definition (JSON) *'}
            </Label>
            <ConfigurationEditor
              ref={configEditorRef}
              type={deploymentType}
              value={definition}
              onChange={setDefinition}
              mode="json"
              error={errors.definition || undefined}
            />
            <p className="text-xs text-muted-foreground mt-1">
              Use ${`{VARIABLE_NAME}`} for variable placeholders
            </p>
          </div>

          {/* Variable Definition Editor */}
          <div>
            <VariableDefinitionEditor
              variables={variables}
              onChange={setVariables}
              definitionText={definition}
            />
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
