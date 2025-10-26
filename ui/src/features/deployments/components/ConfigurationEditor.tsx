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

import { Textarea } from '@/components/ui/textarea'

interface ConfigurationEditorProps {
  type: 'container' | 'stack'
  value: string
  onChange: (value: string) => void
  mode?: 'json'  // Future: add 'form' mode for structured editing
  error?: string | undefined
  className?: string
  rows?: number
}

/**
 * Configuration Editor
 *
 * Adapts placeholder and help text based on deployment type:
 * - Container: Shows image, ports, volumes, environment format
 * - Stack: Shows Docker Compose services format
 */
export function ConfigurationEditor({
  type,
  value,
  onChange,
  // @ts-expect-error - mode reserved for future 'form' editing mode
  mode = 'json',
  error,
  className = '',
  rows = 12
}: ConfigurationEditorProps) {

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
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholders[type]}
        rows={rows}
        className={`font-mono text-sm ${error ? 'border-destructive' : ''} ${className}`}
      />

      {/* Help text */}
      <p className="text-xs text-muted-foreground">
        {helpText[type]}
      </p>

      {/* Error message */}
      {error && (
        <p className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
