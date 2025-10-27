/**
 * Variable Definition Editor Component
 *
 * Allows users to define template variables when creating/editing templates.
 * Features:
 * - Auto-extract variables from ${VAR} placeholders in definition
 * - Manually add/remove variables
 * - Configure variable properties (type, description, default, required)
 * - Validate variable names (uppercase, letters, numbers, underscores only)
 * - Detect orphaned placeholders (${VAR} in definition but no variable defined)
 * - Prevent duplicate variable names
 */

import { useState, useEffect, useRef } from 'react'
import { AlertTriangle, Plus, Trash2, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import type { TemplateVariableConfig } from '../types'

interface VariableDefinitionEditorProps {
  variables: Record<string, TemplateVariableConfig>
  onChange: (variables: Record<string, TemplateVariableConfig>) => void
  definitionText: string  // Current template definition for extracting variables
}

interface VariableRow {
  name: string
  config: TemplateVariableConfig
  errors: string[]
}

export function VariableDefinitionEditor({
  variables,
  onChange,
  definitionText,
}: VariableDefinitionEditorProps) {
  const [variableRows, setVariableRows] = useState<VariableRow[]>([])
  const [orphanedPlaceholders, setOrphanedPlaceholders] = useState<string[]>([])

  // Track if we're syncing to prevent loops
  const isSyncingRef = useRef(false)
  const prevVariablesRef = useRef<Record<string, TemplateVariableConfig>>({})
  const isFirstRenderRef = useRef(true)

  // Initialize variable rows from props when they change externally (not from our own sync)
  useEffect(() => {
    // Skip if we're syncing our own changes back to parent
    if (isSyncingRef.current) {
      isSyncingRef.current = false
      return
    }

    // Check if variables actually changed
    if (JSON.stringify(variables) === JSON.stringify(prevVariablesRef.current)) {
      return
    }

    const rows: VariableRow[] = Object.entries(variables).map(([name, config]) => ({
      name,
      config,
      errors: [],
    }))
    setVariableRows(rows)
    prevVariablesRef.current = variables
  }, [variables])

  // Detect orphaned placeholders whenever definition or variables change
  useEffect(() => {
    const placeholders = extractPlaceholders(definitionText)
    const definedNames = variableRows.map(row => row.name)
    const orphaned = placeholders.filter(name => !definedNames.includes(name))
    setOrphanedPlaceholders(orphaned)
  }, [definitionText, variableRows])

  // Sync variable rows back to parent whenever they change
  // This keeps the parent's state updated so it has the latest data when user clicks Save
  useEffect(() => {
    // Skip on first render - let initialization happen first
    if (isFirstRenderRef.current) {
      isFirstRenderRef.current = false
      return
    }

    const newVariables: Record<string, TemplateVariableConfig> = {}
    variableRows.forEach(row => {
      if (row.name.trim()) {
        newVariables[row.name] = row.config
      }
    })

    // Mark that we're syncing to prevent re-initialization
    isSyncingRef.current = true
    prevVariablesRef.current = newVariables
    onChange(newVariables)
  }, [variableRows, onChange])

  /**
   * Extract ${VAR} placeholders from definition text
   */
  const extractPlaceholders = (text: string): string[] => {
    const pattern = /\$\{([A-Z_][A-Z0-9_]*)\}/g
    const matches = Array.from(text.matchAll(pattern))
    const uniqueNames = new Set(matches.map(m => m[1]).filter((name): name is string => name !== undefined))
    return Array.from(uniqueNames)
  }

  /**
   * Validate variable name format (uppercase letters, numbers, underscores only)
   */
  const validateVariableName = (name: string): string[] => {
    const errors: string[] = []

    if (!name.trim()) {
      errors.push('Variable name is required')
      return errors
    }

    const validPattern = /^[A-Z_][A-Z0-9_]*$/
    if (!validPattern.test(name)) {
      errors.push('Variable name must contain only uppercase letters, numbers, and underscores')
    }

    return errors
  }

  /**
   * Extract variables from definition and add to editor
   */
  const handleExtractVariables = () => {
    const placeholders = extractPlaceholders(definitionText)
    const existingNames = new Set(variableRows.map(row => row.name))

    const newRows: VariableRow[] = []

    placeholders.forEach(name => {
      if (!existingNames.has(name)) {
        newRows.push({
          name,
          config: {
            type: 'string',
            description: '',
            default: '',
            required: false,
          },
          errors: [],
        })
      }
    })

    if (newRows.length > 0) {
      setVariableRows([...variableRows, ...newRows])
    }
  }

  /**
   * Add new empty variable manually
   */
  const handleAddVariable = () => {
    const newRow: VariableRow = {
      name: '',
      config: {
        type: 'string',
        description: '',
        default: '',
        required: false,
      },
      errors: [],
    }
    setVariableRows([...variableRows, newRow])
  }

  /**
   * Remove variable
   */
  const handleRemoveVariable = (index: number) => {
    const updated = variableRows.filter((_, i) => i !== index)
    setVariableRows(updated)
  }

  /**
   * Update variable property
   */
  const handleUpdateVariable = (
    index: number,
    field: keyof VariableRow | keyof TemplateVariableConfig,
    value: any
  ) => {
    const updated = [...variableRows]
    const row = updated[index]

    if (!row) return

    if (field === 'name') {
      row.name = value
      row.errors = validateVariableName(value)

      // Check for duplicates
      const duplicateIndex = updated.findIndex(
        (r, i) => i !== index && r.name === value && value.trim() !== ''
      )
      if (duplicateIndex !== -1) {
        row.errors.push('Duplicate variable name')
      }
    } else {
      // Update config field
      row.config = {
        ...row.config,
        [field]: value,
      }
    }

    setVariableRows(updated)
  }

  const hasPlaceholders = extractPlaceholders(definitionText).length > 0

  return (
    <div className="space-y-4" data-testid="variable-definition-editor">
      {/* Header with actions */}
      <div className="flex items-center justify-between">
        <Label className="text-base font-semibold">Template Variables</Label>
        <div className="flex gap-2">
          {hasPlaceholders && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleExtractVariables}
              data-testid="extract-variables-button"
            >
              <Sparkles className="w-4 h-4 mr-1" />
              Extract Variables
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleAddVariable}
            data-testid="add-variable-button"
          >
            <Plus className="w-4 h-4 mr-1" />
            Add Variable
          </Button>
        </div>
      </div>

      {/* Orphaned placeholders warning */}
      {orphanedPlaceholders.length > 0 && (
        <div
          className="flex items-start gap-2 p-3 bg-yellow-500/10 border border-yellow-500/50 rounded-md text-sm"
          data-testid="orphaned-placeholders-warning"
        >
          <AlertTriangle className="w-4 h-4 text-yellow-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-medium text-yellow-200">Undefined variables detected</p>
            <p className="text-yellow-300 mt-1">
              The following placeholders are used in your definition but have no variable definitions:{' '}
              <code className="font-mono bg-yellow-500/20 px-1 rounded text-yellow-100">
                {orphanedPlaceholders.map(name => `\${${name}}`).join(', ')}
              </code>
            </p>
            <Button
              type="button"
              variant="link"
              size="sm"
              className="text-yellow-200 hover:text-yellow-100 px-0 h-auto"
              onClick={handleExtractVariables}
            >
              Click "Extract Variables" to define them
            </Button>
          </div>
        </div>
      )}

      {/* Variable list */}
      {variableRows.length > 0 ? (
        <div className="space-y-4" data-testid="variables-list">
          {variableRows.map((row, index) => (
            <div
              key={row.name || `new-${index}`}
              className="space-y-2 pb-4 border-b border-border last:border-0 last:pb-0"
              data-testid={`variable-${row.name || `new-${index}`}`}
            >
              {/* Variable name and type row */}
              <div className="grid grid-cols-12 gap-2">
                <div className="col-span-5">
                  <Label htmlFor={`var-name-${index}`} className="text-xs">
                    Variable Name *
                  </Label>
                  <Input
                    id={`var-name-${index}`}
                    data-testid="variable-name-input"
                    value={row.name}
                    onChange={(e) => handleUpdateVariable(index, 'name', e.target.value)}
                    placeholder="MY_VARIABLE"
                    className={row.errors.length > 0 ? 'border-destructive' : ''}
                  />
                  {row.errors.length > 0 && (
                    <p className="text-xs text-destructive mt-1">{row.errors[0]}</p>
                  )}
                </div>

                <div className="col-span-3">
                  <Label htmlFor={`var-type-${index}`} className="text-xs">
                    Type
                  </Label>
                  <Select
                    value={row.config.type || 'string'}
                    onValueChange={(value) => handleUpdateVariable(index, 'type', value)}
                  >
                    <SelectTrigger
                      id={`var-type-${index}`}
                      data-testid="variable-type-select"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="string">String</SelectItem>
                      <SelectItem value="integer">Integer</SelectItem>
                      <SelectItem value="boolean">Boolean</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="col-span-3">
                  <Label htmlFor={`var-default-${index}`} className="text-xs">
                    Default Value
                  </Label>
                  <Input
                    id={`var-default-${index}`}
                    data-testid="variable-default-input"
                    value={row.config.default || ''}
                    onChange={(e) => handleUpdateVariable(index, 'default', e.target.value)}
                    placeholder="Optional"
                  />
                </div>

                <div className="col-span-1 flex items-end justify-center">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => handleRemoveVariable(index)}
                    data-testid="delete-variable-button"
                    title="Delete variable"
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </div>

              {/* Description and Required checkbox row */}
              <div className="grid grid-cols-12 gap-2">
                <div className="col-span-10">
                  <Label htmlFor={`var-desc-${index}`} className="text-xs">
                    Description
                  </Label>
                  <Textarea
                    id={`var-desc-${index}`}
                    data-testid="variable-description-input"
                    value={row.config.description || ''}
                    onChange={(e) => handleUpdateVariable(index, 'description', e.target.value)}
                    placeholder="Explain what this variable is used for..."
                    rows={2}
                    className="resize-none"
                  />
                </div>
                <div className="col-span-2 flex items-end">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id={`var-required-${index}`}
                      data-testid="variable-required-checkbox"
                      checked={row.config.required || false}
                      onCheckedChange={(checked) =>
                        handleUpdateVariable(index, 'required', checked)
                      }
                    />
                    <Label
                      htmlFor={`var-required-${index}`}
                      className="text-xs font-normal cursor-pointer whitespace-nowrap"
                    >
                      Required
                    </Label>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-muted-foreground">
          <p className="text-sm">No variables defined yet</p>
          <p className="text-xs mt-1">
            Use <code className="font-mono bg-muted px-1 rounded">${'{VARIABLE_NAME}'}</code> in
            your definition, then click "Extract Variables"
          </p>
        </div>
      )}

      {/* Helper text */}
      <p className="text-xs text-muted-foreground">
        Variables allow template reuse with different values. Use{' '}
        <code className="font-mono bg-muted px-1 rounded">${'{VARIABLE_NAME}'}</code> syntax in
        your template definition.
      </p>
    </div>
  )
}
