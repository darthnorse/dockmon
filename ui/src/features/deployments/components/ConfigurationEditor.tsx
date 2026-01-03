/**
 * Configuration Editor Component
 *
 * Shared component for editing deployment configurations (container or stack).
 * Provides type-specific placeholders and help text.
 *
 * Used by:
 * - TemplateForm (create/edit templates)
 * - DeploymentForm (create/edit deployments)
 */

import { useState, useImperativeHandle, forwardRef } from 'react'
import { Wand2, CheckCircle2 } from 'lucide-react'
import yaml from 'js-yaml'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'

interface ConfigurationEditorProps {
  type: 'container' | 'stack'
  value: string
  onChange: (value: string) => void
  mode?: 'json'  // Future: add 'form' mode for structured editing
  error?: string | undefined
  className?: string
  rows?: number
}

export interface ConfigurationEditorHandle {
  validate: () => { valid: boolean; error: string | null }
  format: () => string | null  // Returns formatted content, or null if format failed
}

/**
 * Configuration Editor
 *
 * Adapts placeholder and help text based on deployment type:
 * - Container: Shows image, ports, volumes, environment format
 * - Stack: Shows Docker Compose services format
 */
export const ConfigurationEditor = forwardRef<ConfigurationEditorHandle, ConfigurationEditorProps>(({
  type,
  value,
  onChange,
  // @ts-expect-error - mode reserved for future 'form' editing mode
  mode = 'json',
  error,
  className = '',
  rows = 12
}, ref) => {
  const [formatStatus, setFormatStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [validationError, setValidationError] = useState<string | null>(null)

  /**
   * Validate content without formatting
   * Returns validation result for form submission
   * Note: Use format() function for auto-fix with corrected content
   */
  const validateContent = (): { valid: boolean; error: string | null } => {
    if (!value.trim()) {
      return { valid: true, error: null } // Empty is valid (will be caught by form validation)
    }

    try {
      if (type === 'stack') {
        // Try parsing YAML as-is
        try {
          yaml.load(value)
          return { valid: true, error: null }
        } catch (firstErr: any) {
          // If parsing failed with indentation error, try auto-fix
          if (firstErr.message?.includes('bad indentation') ||
              firstErr.message?.includes('expected <block end>')) {
            const fixedYaml = autoFixYamlIndentation(value)

            if (fixedYaml) {
              try {
                yaml.load(fixedYaml)
                return { valid: true, error: null }
              } catch (secondErr: any) {
                return { valid: false, error: firstErr.message }
              }
            }
          }
          return { valid: false, error: firstErr.message }
        }
      } else {
        // Validate JSON
        JSON.parse(value)
        return { valid: true, error: null }
      }
    } catch (err: any) {
      return { valid: false, error: err.message || 'Invalid format' }
    }
  }

  // Format content (auto-fix + prettify) - returns formatted content or null if failed
  const formatContent = (): string | null => {
    if (!value.trim()) {
      return null
    }

    try {
      if (type === 'stack') {
        let contentToFormat = value

        // First attempt: Parse as-is
        try {
          const parsed = yaml.load(contentToFormat)
          const formatted = yaml.dump(parsed, {
            indent: 2,
            lineWidth: -1,
            noRefs: true,
            sortKeys: false
          })

          return formatted
        } catch (firstErr: any) {
          // If parsing failed with indentation error, try auto-fix
          if (firstErr.message?.includes('bad indentation') ||
              firstErr.message?.includes('expected <block end>')) {
            const fixedYaml = autoFixYamlIndentation(contentToFormat)

            if (fixedYaml) {
              try {
                const parsed = yaml.load(fixedYaml)
                const formatted = yaml.dump(parsed, {
                  indent: 2,
                  lineWidth: -1,
                  noRefs: true,
                  sortKeys: false
                })

                return formatted
              } catch (secondErr: any) {
                return null
              }
            }
          }
          return null
        }
      } else {
        // Parse and format JSON
        const parsed = JSON.parse(value)
        const formatted = JSON.stringify(parsed, null, 2)
        return formatted
      }
    } catch (err: any) {
      return null
    }
  }

  // Expose validate and format functions to parent via ref
  useImperativeHandle(ref, () => ({
    validate: validateContent,
    format: formatContent
  }))

  /**
   * Auto-fix common YAML indentation issues in Docker Compose files
   * Handles root-level keys (services, volumes, networks) that are incorrectly indented
   */
  const autoFixYamlIndentation = (yamlContent: string): string | null => {
    const lines = yamlContent.split('\n')

    // Docker Compose root-level keys that must be at column 0
    const rootLevelKeys = ['services:', 'volumes:', 'networks:', 'configs:', 'secrets:', 'version:']

    // First pass: Find ACTUAL root-level keys (only those with minimal indentation, likely mistakes)
    // True root keys should have 0-2 spaces of indentation (2 being the mistake we're fixing)
    const rootKeyIndents: Map<number, number> = new Map()

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      if (!line) continue

      const trimmed = line.trim()
      const currentIndent = line.match(/^(\s*)/)?.[1]?.length || 0

      // Check if this is a root-level key
      const isRootKey = rootLevelKeys.some(key => trimmed === key)

      if (isRootKey && currentIndent > 0 && currentIndent <= 2) {
        // This is likely a root-level key that's incorrectly indented
        // Service-level keys (volumes/networks inside a service) are typically indented 4+ spaces
        rootKeyIndents.set(i, currentIndent)
      }
    }

    // If no indented root keys found, no fixes needed
    if (rootKeyIndents.size === 0) {
      return null
    }

    // Second pass: Fix indentation by removing the base indent from affected sections
    const fixedLines: string[] = []
    let currentRootKeyLine = -1
    let indentToRemove = 0

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      if (line === undefined) continue  // Type safety guard (split() should not produce undefined)

      const trimmed = line.trim()
      const currentIndent = line.match(/^(\s*)/)?.[1]?.length || 0

      // Check if this is one of our identified root keys
      if (rootKeyIndents.has(i)) {
        currentRootKeyLine = i
        indentToRemove = rootKeyIndents.get(i)!
        // Move to column 0
        fixedLines.push(trimmed)
        continue
      }

      // Check if we hit a different root-level key (end of current section)
      const isRootKey = rootLevelKeys.some(key => trimmed === key)
      if (isRootKey && currentIndent <= 2 && !rootKeyIndents.has(i)) {
        currentRootKeyLine = -1
        indentToRemove = 0
        fixedLines.push(line)
        continue
      }

      // Preserve empty lines and document separators
      if (!trimmed || trimmed === '---') {
        fixedLines.push(line)
        continue
      }

      // Preserve comments
      if (trimmed.startsWith('#')) {
        fixedLines.push(line)
        continue
      }

      // For content under an indented root key, remove the base indent
      if (currentRootKeyLine >= 0 && indentToRemove > 0) {
        if (currentIndent >= indentToRemove) {
          // Remove the base indent
          const newIndent = currentIndent - indentToRemove
          const newLine = ' '.repeat(newIndent) + trimmed
          fixedLines.push(newLine)
        } else {
          // Line has less indent than expected, add minimal indent
          fixedLines.push('  ' + trimmed)
        }
      } else {
        // Not under an indented root key, keep as-is
        fixedLines.push(line)
      }
    }

    return fixedLines.join('\n')
  }

  /**
   * Format and validate YAML (for stacks) or JSON (for containers)
   * For YAML: Attempts auto-fix of common indentation issues before validation
   */
  const handleFormat = () => {
    const formatted = formatContent()

    if (formatted) {
      onChange(formatted)
      setValidationError(null)
      setFormatStatus('success')
      setTimeout(() => setFormatStatus('idle'), 2000)
    } else {
      setValidationError('Invalid format - could not auto-fix')
      setFormatStatus('error')
      setTimeout(() => setFormatStatus('idle'), 2000)

      // Show helpful message for YAML errors
      if (type === 'stack') {
        let helpfulMessage = 'Invalid YAML format'

        // Check for common YAML indentation errors
        try {
          yaml.load(value)
        } catch (err: any) {
          if (err.message?.includes('bad indentation')) {
            helpfulMessage += '\n\nTip: Root-level keys (services, volumes, networks) must have NO indentation (column 0).'
          }
        }

        setValidationError(helpfulMessage)
      }
    }
  }

  // Type-specific placeholders
  const placeholders = {
    container: JSON.stringify({
      image: 'nginx:latest',
      ports: ['80:80', '443:443'],
      volumes: ['/host/path:/container/path'],
      environment: {
        ENV_VAR: 'value'
      },
      restart: 'unless-stopped'
    }, null, 2),

    stack: `---
services:
  web:
    image: nginx:latest
    ports:
      - "80:80"
      - "443:443"

  db:
    image: postgres:14
    environment:
      POSTGRES_PASSWORD: secret

networks:
  default:
    driver: bridge`
  }

  // Type-specific help text
  const helpText = {
    container: 'Container deployment JSON: specify image, ports, volumes, environment variables, and restart policy',
    stack: 'Docker Compose YAML: define multiple services, networks, and volumes in YAML format'
  }

  return (
    <div className="space-y-2">
      {/* Format Button */}
      <div className="flex justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleFormat}
          disabled={!value.trim()}
          className="gap-2"
        >
          {formatStatus === 'success' ? (
            <>
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              Formatted
            </>
          ) : formatStatus === 'error' ? (
            <>
              <Wand2 className="h-4 w-4 text-destructive" />
              Invalid {type === 'stack' ? 'YAML' : 'JSON'}
            </>
          ) : (
            <>
              <Wand2 className="h-4 w-4" />
              Format & Validate
            </>
          )}
        </Button>
      </div>

      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          // Allow Tab key to insert spaces instead of moving focus (Issue #126)
          if (e.key === 'Tab') {
            e.preventDefault()
            const target = e.target as HTMLTextAreaElement
            const start = target.selectionStart
            const end = target.selectionEnd

            // Insert 2 spaces at cursor position
            const newValue = value.substring(0, start) + '  ' + value.substring(end)
            onChange(newValue)

            // Move cursor after the inserted spaces
            requestAnimationFrame(() => {
              target.selectionStart = target.selectionEnd = start + 2
            })
          }
        }}
        placeholder={placeholders[type]}
        rows={rows}
        className={`font-mono text-sm ${error || validationError ? 'border-destructive' : ''} ${className}`}
      />

      {/* Help text */}
      <p className="text-xs text-muted-foreground">
        {helpText[type]}
      </p>

      {/* Validation error (from Format button) */}
      {validationError && (
        <p className="text-xs text-destructive">
          {validationError}
        </p>
      )}

      {/* Form validation error (from parent) */}
      {error && (
        <p className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
})

ConfigurationEditor.displayName = 'ConfigurationEditor'
