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

import { useState, useImperativeHandle, forwardRef, useCallback, useMemo } from 'react'
import { Wand2, CheckCircle2 } from 'lucide-react'
import yaml from 'js-yaml'
import CodeMirror from '@uiw/react-codemirror'
import { yaml as yamlLang } from '@codemirror/lang-yaml'
import { json as jsonLang } from '@codemirror/lang-json'
import * as themes from '@uiw/codemirror-themes-all'
import { Button } from '@/components/ui/button'
import { useGlobalSettings } from '@/hooks/useSettings'

// Type guard for services object
function isServicesRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/**
 * Validate compose-specific requirements
 * Returns error if invalid, warning if there's a non-blocking issue, null otherwise
 */
function validateComposeContent(parsed: unknown): { error?: string; warning?: string } {
  if (!parsed || typeof parsed !== 'object') {
    return { error: 'Compose file must be a valid YAML object' }
  }

  const compose = parsed as Record<string, unknown>

  // Check for required 'services' section
  if (!('services' in compose) || !compose.services) {
    return { error: "Compose file must contain a 'services' section" }
  }

  // Verify services is an object (not array or primitive)
  if (!isServicesRecord(compose.services)) {
    return { error: "'services' must be an object containing service definitions" }
  }

  // Check for 'build' directives (warning - works locally but not on agent hosts)
  const servicesWithBuild: string[] = []
  for (const [serviceName, serviceConfig] of Object.entries(compose.services)) {
    if (isServicesRecord(serviceConfig) && 'build' in serviceConfig) {
      servicesWithBuild.push(serviceName)
    }
  }

  if (servicesWithBuild.length > 0) {
    return {
      warning: `Warning: 'build' directive found in service(s): ${servicesWithBuild.join(', ')}. This will not work on agent-based hosts.`
    }
  }

  return {}
}

// Theme mapping for CodeMirror (dark themes only)
const EDITOR_THEMES = {
  'github-dark': themes.githubDark,
  'vscode-dark': themes.vscodeDark,
  'dracula': themes.dracula,
  'material-dark': themes.materialDark,
  'nord': themes.nord,
  'atomone': themes.atomone,
  'aura': themes.aura,
  'andromeda': themes.andromeda,
  'copilot': themes.copilot,
  'gruvbox-dark': themes.gruvboxDark,
  'monokai': themes.monokai,
  'solarized-dark': themes.solarizedDark,
  'sublime': themes.sublime,
  'tokyo-night': themes.tokyoNight,
  'tokyo-night-storm': themes.tokyoNightStorm,
  'okaidia': themes.okaidia,
  'abyss': themes.abyss,
  'kimbie': themes.kimbie,
} as const

interface ConfigurationEditorProps {
  type: 'container' | 'stack'
  value: string
  onChange: (value: string) => void
  mode?: 'json'  // Future: add 'form' mode for structured editing
  error?: string | undefined
  className?: string
  rows?: number
  fillHeight?: boolean  // If true, fills available height instead of using rows
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
  rows = 12,
  fillHeight = false
}, ref) => {
  const [formatStatus, setFormatStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [validationError, setValidationError] = useState<string | null>(null)
  const [validationWarning, setValidationWarning] = useState<string | null>(null)
  const { data: globalSettings } = useGlobalSettings()

  // Get the selected theme (memoized to avoid recreation on every render)
  const editorTheme = useMemo(() => {
    const themeName = globalSettings?.editor_theme ?? 'aura'
    return EDITOR_THEMES[themeName as keyof typeof EDITOR_THEMES] ?? themes.githubDark
  }, [globalSettings?.editor_theme])

  // Stable callback for CodeMirror onChange - clears validation state when user edits
  const handleChange = useCallback((val: string) => {
    onChange(val)
    // Clear validation state when content changes - user may have fixed the issue
    setValidationError(null)
    setValidationWarning(null)
    setFormatStatus('idle')
  }, [onChange])

  /**
   * Validate content without formatting
   * Returns validation result for form submission
   * Note: Use format() function for auto-fix with corrected content
   */
  const validateContent = (): { valid: boolean; error: string | null; warning?: string } => {
    if (!value.trim()) {
      return { valid: true, error: null } // Empty is valid (will be caught by form validation)
    }

    try {
      if (type === 'stack') {
        // Try parsing YAML as-is
        let parsed: unknown
        try {
          parsed = yaml.load(value)
        } catch (firstErr: unknown) {
          const firstErrMsg = firstErr instanceof Error ? firstErr.message : String(firstErr)
          // If parsing failed with indentation error, try auto-fix
          if (firstErrMsg.includes('bad indentation') ||
              firstErrMsg.includes('expected <block end>')) {
            const fixedYaml = autoFixYamlIndentation(value)

            if (fixedYaml) {
              try {
                parsed = yaml.load(fixedYaml)
              } catch {
                return { valid: false, error: firstErrMsg }
              }
            } else {
              return { valid: false, error: firstErrMsg }
            }
          } else {
            return { valid: false, error: firstErrMsg }
          }
        }

        // Compose-specific validation using shared helper
        const composeResult = validateComposeContent(parsed)
        if (composeResult.error) {
          return { valid: false, error: composeResult.error }
        }
        if (composeResult.warning) {
          return { valid: true, error: null, warning: composeResult.warning }
        }
        return { valid: true, error: null }
      } else {
        // Validate JSON
        JSON.parse(value)
        return { valid: true, error: null }
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Invalid format'
      return { valid: false, error: errMsg }
    }
  }

  // Format content (auto-fix + prettify) - returns formatted content or null if failed
  const formatContent = (): string | null => {
    if (!value.trim()) {
      return null
    }

    try {
      if (type === 'stack') {
        const contentToFormat = value

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
        } catch (firstErr: unknown) {
          const firstErrMsg = firstErr instanceof Error ? firstErr.message : String(firstErr)
          // If parsing failed with indentation error, try auto-fix
          if (firstErrMsg.includes('bad indentation') ||
              firstErrMsg.includes('expected <block end>')) {
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
              } catch {
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
    } catch {
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
      setValidationWarning(null)

      // Run compose-specific validation on formatted content
      if (type === 'stack') {
        try {
          const parsed = yaml.load(formatted)
          const composeResult = validateComposeContent(parsed)
          if (composeResult.error) {
            setValidationError(composeResult.error)
            setFormatStatus('error')
            setTimeout(() => setFormatStatus('idle'), 2000)
            return
          }
          if (composeResult.warning) {
            // Strip "Warning: " prefix for display (helper adds it)
            setValidationWarning(composeResult.warning.replace(/^Warning:\s*/, ''))
          }
        } catch {
          // YAML parsing error - shouldn't happen since formatContent succeeded
        }
      }

      setFormatStatus('success')
      setTimeout(() => setFormatStatus('idle'), 2000)
    } else {
      setValidationError('Invalid format - could not auto-fix')
      setValidationWarning(null)
      setFormatStatus('error')
      setTimeout(() => setFormatStatus('idle'), 2000)

      // Show helpful message for YAML errors
      if (type === 'stack') {
        let helpfulMessage = 'Invalid YAML format'

        // Check for common YAML indentation errors
        try {
          yaml.load(value)
        } catch (err: unknown) {
          const errMsg = err instanceof Error ? err.message : String(err)
          if (errMsg.includes('bad indentation')) {
            helpfulMessage += '\n\nTip: Root-level keys (services, volumes, networks) must have NO indentation (column 0).'
          }
        }

        // Also check for compose-specific issues (missing services, etc.)
        try {
          const parsed = yaml.load(value)
          const composeResult = validateComposeContent(parsed)
          if (composeResult.error) {
            helpfulMessage = composeResult.error
          }
        } catch {
          // Keep the YAML error message
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
    <div className={fillHeight ? 'flex flex-col h-full' : 'space-y-2'}>
      {/* Format Button */}
      <div className={`flex justify-end ${fillHeight ? 'mb-2 shrink-0' : ''}`}>
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

      <CodeMirror
        value={value}
        onChange={handleChange}
        extensions={type === 'stack' ? [yamlLang()] : [jsonLang()]}
        theme={editorTheme}
        placeholder={placeholders[type]}
        height={fillHeight ? '100%' : `${rows * 1.5}rem`}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: true,
          indentOnInput: true,
          tabSize: 2,
        }}
        className={`rounded-md border ${error || validationError ? 'border-destructive' : 'border-input'} ${fillHeight ? 'flex-1 min-h-0' : ''} ${className}`}
      />

      {/* Help text */}
      <p className={`text-xs text-muted-foreground ${fillHeight ? 'mt-2 shrink-0' : ''}`}>
        {helpText[type]}
      </p>

      {/* Validation error (from Format button) */}
      {validationError && (
        <p className={`text-xs text-destructive ${fillHeight ? 'shrink-0' : ''}`}>
          {validationError}
        </p>
      )}

      {/* Validation warning (from Format button) */}
      {validationWarning && !validationError && (
        <p className={`text-xs text-warning ${fillHeight ? 'shrink-0' : ''}`}>
          {validationWarning}
        </p>
      )}

      {/* Form validation error (from parent) */}
      {error && (
        <p className={`text-xs text-destructive ${fillHeight ? 'shrink-0' : ''}`}>
          {error}
        </p>
      )}
    </div>
  )
})

ConfigurationEditor.displayName = 'ConfigurationEditor'
