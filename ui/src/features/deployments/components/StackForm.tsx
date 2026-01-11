/**
 * Stack Form Component (v2.2.7+)
 *
 * Create or edit stacks (filesystem-based compose configurations).
 * - Stack name (lowercase alphanumeric, hyphens, underscores)
 * - Compose YAML content
 * - Optional .env file content
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
import { useStack, useCreateStack, useUpdateStack } from '../hooks/useStacks'
import { ConfigurationEditor, ConfigurationEditorHandle } from './ConfigurationEditor'
import { validateStackName, MAX_STACK_NAME_LENGTH } from '../types'

interface StackFormProps {
  isOpen: boolean
  onClose: () => void
  stackName?: string | null  // If provided, edit mode
}

export function StackForm({ isOpen, onClose, stackName }: StackFormProps) {
  const createStack = useCreateStack()
  const updateStack = useUpdateStack()

  // Fetch existing stack data in edit mode
  const { data: existingStack, isLoading: isLoadingStack } = useStack(stackName || null)

  const isEditMode = !!stackName

  // Form state
  const [name, setName] = useState('')
  const [composeYaml, setComposeYaml] = useState('')
  const [envContent, setEnvContent] = useState('')

  // Validation errors
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Ref to ConfigurationEditor for validation
  const configEditorRef = useRef<ConfigurationEditorHandle>(null)

  // Load stack data in edit mode
  useEffect(() => {
    if (existingStack && isOpen) {
      setName(existingStack.name)
      setComposeYaml(existingStack.compose_yaml || '')
      setEnvContent(existingStack.env_content || '')
    }
  }, [existingStack, isOpen])

  // Reset form when closed
  useEffect(() => {
    if (!isOpen) {
      setName('')
      setComposeYaml('')
      setEnvContent('')
      setErrors({})
    }
  }, [isOpen])

  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {}

    // Use shared validation utility
    const nameError = validateStackName(name)
    if (nameError) {
      newErrors.name = nameError
    }

    if (!composeYaml.trim()) {
      newErrors.composeYaml = 'Compose YAML is required'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!validateForm()) {
      return
    }

    // Validate YAML configuration before saving
    if (configEditorRef.current && composeYaml.trim()) {
      const validation = configEditorRef.current.validate()
      if (!validation.valid) {
        setErrors({
          ...errors,
          composeYaml: validation.error || 'Invalid YAML format. Please fix errors before saving.',
        })
        return
      }
    }

    try {
      if (isEditMode && stackName) {
        // Update existing stack
        await updateStack.mutateAsync({
          name: stackName,
          compose_yaml: composeYaml,
          env_content: envContent.trim() || null,
        })
      } else {
        // Create new stack
        await createStack.mutateAsync({
          name: name.trim(),
          compose_yaml: composeYaml,
          env_content: envContent.trim() || null,
        })
      }

      onClose()
    } catch (error: unknown) {
      // Check for duplicate name error
      const errorMessage = error instanceof Error ? error.message : String(error)
      if (errorMessage.includes('already exists')) {
        setErrors({
          ...errors,
          name: 'A stack with this name already exists. Please choose a different name.',
        })
        return // Keep form open so user can fix the error
      }
      // Other errors handled by hook's onError
    }
  }

  // Show loading state while fetching existing stack
  const isLoading = isEditMode && isLoadingStack

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="stack-form">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? 'Edit Stack' : 'Create Stack'}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? 'Update the stack compose configuration'
              : 'Create a new stack with Docker Compose YAML'}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="py-8 text-center text-muted-foreground">
            Loading stack...
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Name */}
            <div>
              <Label htmlFor="name">Stack Name *</Label>
              <Input
                id="name"
                name="name"
                value={name}
                onChange={(e) => setName(e.target.value.toLowerCase())}
                placeholder="e.g., my-web-app"
                className={`font-mono ${errors.name ? 'border-destructive' : ''}`}
                disabled={isEditMode} // Can't rename via this form
                maxLength={MAX_STACK_NAME_LENGTH}
              />
              {errors.name && (
                <p className="text-sm text-destructive mt-1">{errors.name}</p>
              )}
              <p className="text-xs text-muted-foreground mt-1">
                Lowercase letters, numbers, hyphens, and underscores only
              </p>
            </div>

            {/* Compose YAML */}
            <div>
              <Label htmlFor="compose-yaml">Compose YAML *</Label>
              <ConfigurationEditor
                ref={configEditorRef}
                type="stack"
                value={composeYaml}
                onChange={setComposeYaml}
                error={errors.composeYaml || undefined}
                rows={14}
              />
            </div>

            {/* Environment Variables */}
            <div>
              <Label htmlFor="env-content">Environment Variables (.env)</Label>
              <Textarea
                id="env-content"
                name="env-content"
                value={envContent}
                onChange={(e) => setEnvContent(e.target.value)}
                placeholder={`# Optional .env file content\nDATABASE_URL=postgres://...\nAPI_KEY=your-secret-key`}
                rows={6}
                className="font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Optional environment variables for Compose variable substitution
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
                disabled={createStack.isPending || updateStack.isPending}
              >
                {createStack.isPending || updateStack.isPending
                  ? 'Saving...'
                  : isEditMode ? 'Save Changes' : 'Create Stack'}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
