/**
 * Variable Input Dialog Component
 *
 * Dialog for collecting template variable values
 * - Displays all variables from template
 * - Shows defaults and descriptions
 * - Validates required variables
 */

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { DeploymentTemplate, TemplateVariableConfig } from '../types'

interface VariableInputDialogProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (values: Record<string, any>) => void
  template: DeploymentTemplate | null
}

export function VariableInputDialog({
  isOpen,
  onClose,
  onSubmit,
  template,
}: VariableInputDialogProps) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Initialize values with defaults when template changes
  useEffect(() => {
    if (template && template.variables) {
      const defaultValues: Record<string, string> = {}

      Object.entries(template.variables).forEach(([name, config]: [string, TemplateVariableConfig]) => {
        if (config.default !== undefined) {
          defaultValues[name] = String(config.default)
        }
      })

      setValues(defaultValues)
      setErrors({})
    }
  }, [template])

  const validateForm = (): boolean => {
    if (!template || !template.variables) return true

    const newErrors: Record<string, string> = {}

    Object.entries(template.variables).forEach(([name, config]: [string, TemplateVariableConfig]) => {
      if (config.required && !values[name]?.trim()) {
        newErrors[name] = `${name} is required`
      }
    })

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    if (!validateForm()) {
      return
    }

    // Convert values to appropriate types
    const typedValues: Record<string, any> = {}

    if (template && template.variables) {
      Object.entries(values).forEach(([name, value]) => {
        const config = template.variables[name]

        if (!config) {
          typedValues[name] = value
          return
        }

        switch (config.type) {
          case 'integer':
            typedValues[name] = parseInt(value, 10) || 0
            break
          case 'boolean':
            typedValues[name] = value === 'true' || value === '1'
            break
          default:
            typedValues[name] = value
        }
      })
    }

    onSubmit(typedValues)
    onClose()
  }

  const handleCancel = () => {
    setValues({})
    setErrors({})
    onClose()
  }

  if (!template) return null

  // No variables to fill in
  if (!template.variables || Object.keys(template.variables).length === 0) {
    return null
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleCancel}>
      <DialogContent className="max-w-2xl" data-testid="template-variables-form">
        <DialogHeader>
          <DialogTitle>Template Variables</DialogTitle>
          <DialogDescription>
            Configure variables for "{template.name}"
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {Object.entries(template.variables).map(([name, config]: [string, TemplateVariableConfig]) => (
            <div key={name} className="space-y-2">
              <Label htmlFor={`var-${name}`}>
                {name}
                {config.required && <span className="text-destructive ml-1">*</span>}
              </Label>

              {config.description && (
                <p className="text-sm text-muted-foreground">{config.description}</p>
              )}

              <Input
                id={`var-${name}`}
                name={name}
                value={values[name] || ''}
                onChange={(e) => setValues({ ...values, [name]: e.target.value })}
                placeholder={config.default !== undefined ? String(config.default) : ''}
                className={errors[name] ? 'border-destructive' : ''}
              />

              {errors[name] && (
                <p className="text-sm text-destructive">{errors[name]}</p>
              )}

              {config.default !== undefined && (
                <p className="text-xs text-muted-foreground">
                  Default: {String(config.default)}
                </p>
              )}
            </div>
          ))}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={handleCancel}>
              Cancel
            </Button>
            <Button type="submit">
              Use Template
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
