/**
 * Deployment Form Component
 *
 * Form for creating/editing container deployments
 * - Supports container and stack deployments
 * - Template selection
 * - Security validation warnings
 * - Field validation
 */

import { useState, useEffect, useRef } from 'react'
import { AlertTriangle, AlertCircle, Layers } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useCreateDeployment, useUpdateDeployment } from '../hooks/useDeployments'
import { useRenderTemplate, useCreateTemplate } from '../hooks/useTemplates'
import { TemplateSelector } from './TemplateSelector'
import { VariableInputDialog } from './VariableInputDialog'
import { ConfigurationEditor, ConfigurationEditorHandle } from './ConfigurationEditor'
import type { DeploymentType, DeploymentDefinition, DeploymentTemplate, Deployment } from '../types'

interface DeploymentFormProps {
  isOpen: boolean
  onClose: () => void
  hosts?: Array<{ id: string; name: string }>  // Available hosts
  deployment?: Deployment  // If provided, form is in edit mode
}

export function DeploymentForm({ isOpen, onClose, hosts = [], deployment }: DeploymentFormProps) {
  const createDeployment = useCreateDeployment()
  const updateDeployment = useUpdateDeployment()
  const renderTemplate = useRenderTemplate()
  const createTemplate = useCreateTemplate()

  const isEditMode = !!deployment

  // Form state
  const [name, setName] = useState('')
  const [type, setType] = useState<DeploymentType>('container')
  const [hostId, setHostId] = useState('')
  const [image, setImage] = useState('')
  const [ports, setPorts] = useState('')
  const [volumes, setVolumes] = useState('')
  const [environment, setEnvironment] = useState('')
  const [labels, setLabels] = useState('')
  const [privileged, setPrivileged] = useState(false)
  const [networkMode, setNetworkMode] = useState('bridge')
  const [capabilities, setCapabilities] = useState('')
  const [memoryLimit, setMemoryLimit] = useState('')
  const [cpuLimit, setCpuLimit] = useState('')
  const [restartPolicy, setRestartPolicy] = useState('unless-stopped')

  // Stack state
  const [composeYaml, setComposeYaml] = useState('')

  // Template state
  const [showTemplateSelector, setShowTemplateSelector] = useState(false)
  const [showVariableInput, setShowVariableInput] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState<DeploymentTemplate | null>(null)

  // Save as Template state
  const [saveAsTemplate, setSaveAsTemplate] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const [templateCategory, setTemplateCategory] = useState('')
  const [templateDescription, setTemplateDescription] = useState('')

  // Validation errors
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Security warnings
  const [securityWarnings, setSecurityWarnings] = useState<string[]>([])

  // Ref to ConfigurationEditor for validation
  const configEditorRef = useRef<ConfigurationEditorHandle>(null)

  // Reset form when closed (but not when opening in edit mode)
  useEffect(() => {
    if (!isOpen) {
      setName('')
      setType('container')
      setHostId('')
      setImage('')
      setPorts('')
      setVolumes('')
      setEnvironment('')
      setLabels('')
      setPrivileged(false)
      setNetworkMode('bridge')
      setCapabilities('')
      setMemoryLimit('')
      setCpuLimit('')
      setRestartPolicy('unless-stopped')
      setComposeYaml('')
      setErrors({})
      setSecurityWarnings([])
      setSelectedTemplate(null)
      setShowTemplateSelector(false)
      setShowVariableInput(false)
      setSaveAsTemplate(false)
      setTemplateName('')
      setTemplateCategory('')
      setTemplateDescription('')
    }
  }, [isOpen])

  // Populate form when in edit mode - MUST run when dialog opens
  useEffect(() => {
    if (isOpen && isEditMode && deployment && deployment.definition) {
      console.log('[DeploymentForm] Populating form for edit mode:', {
        name: deployment.name,
        type: deployment.deployment_type,
        definition: deployment.definition
      })

      setName(deployment.name)
      setType(deployment.deployment_type)  // This sets type to 'stack'
      setHostId(deployment.host_id)

      const def = deployment.definition as DeploymentDefinition

      // Stack fields (check first so we set the YAML before rendering)
      if (def.compose_yaml) {
        console.log('[DeploymentForm] Setting compose YAML:', def.compose_yaml.substring(0, 100))
        setComposeYaml(def.compose_yaml)
      }

      // Container fields
      if (def.image) setImage(def.image)
      if (def.ports) setPorts(Array.isArray(def.ports) ? def.ports.join(', ') : '')
      if (def.volumes) setVolumes(Array.isArray(def.volumes) ? def.volumes.join(', ') : '')
      if (def.environment) {
        const envStr = Object.entries(def.environment).map(([k, v]) => `${k}=${v}`).join('\n')
        setEnvironment(envStr)
      }
      if (def.labels) {
        const labelStr = Object.entries(def.labels).map(([k, v]) => `${k}=${v}`).join('\n')
        setLabels(labelStr)
      }
      if (def.privileged !== undefined) setPrivileged(def.privileged)
      if (def.network_mode) setNetworkMode(def.network_mode)
      if (def.cap_add) setCapabilities(def.cap_add.join(', '))
      if (def.memory_limit) setMemoryLimit(def.memory_limit)
      if (def.cpu_limit) setCpuLimit(def.cpu_limit)
      if (def.restart_policy) setRestartPolicy(def.restart_policy)
    }
  }, [isOpen, isEditMode, deployment])

  // Set default host if only one available
  useEffect(() => {
    if (hosts && hosts.length === 1 && !hostId && hosts[0]) {
      setHostId(hosts[0].id)
    }
  }, [hosts, hostId])

  // Check for security issues
  useEffect(() => {
    const warnings: string[] = []

    if (privileged) {
      warnings.push('Privileged mode grants full access to host system')
    }

    if (volumes.includes('/var/run/docker.sock')) {
      warnings.push('Mounting docker.sock grants container control over Docker')
    }

    if (networkMode === 'host') {
      warnings.push('Host network mode bypasses network isolation')
    }

    if (capabilities.includes('SYS_ADMIN') || capabilities.includes('SYS_MODULE')) {
      warnings.push('Dangerous capabilities may compromise host security')
    }

    setSecurityWarnings(warnings)
  }, [privileged, volumes, networkMode, capabilities])

  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {}

    if (!name.trim()) {
      newErrors.name = 'Deployment name is required'
    } else if (name.includes(' ')) {
      newErrors.name = 'Deployment name cannot contain spaces'
    }

    if (!hostId) {
      newErrors.hostId = 'Please select a host'
    }

    if (type === 'container' && !image.trim()) {
      newErrors.image = 'Image is required for container deployments'
    }

    if (type === 'stack' && !composeYaml.trim()) {
      newErrors.compose_yaml = 'Docker Compose YAML is required for stack deployments'
    }

    // Validate port format
    if (ports) {
      const portMappings = ports.split(',').map(p => p.trim()).filter(Boolean)
      for (const port of portMappings) {
        if (!/^\d+:\d+(\/tcp|\/udp)?$/.test(port)) {
          newErrors.ports = `Invalid port format: ${port}. Use format: 8080:80`
          break
        }
      }
    }

    // Validate volume format
    if (volumes) {
      const volumeMappings = volumes.split(',').map(v => v.trim()).filter(Boolean)
      for (const volume of volumeMappings) {
        if (!volume.includes(':')) {
          newErrors.volumes = `Invalid volume format: ${volume}. Use format: /host:/container`
          break
        }
      }
    }

    // Validate template name if "Save as Template" is enabled
    if (saveAsTemplate && !templateName.trim()) {
      newErrors.templateName = 'Template name is required when saving as template'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  // Handle template selection
  const handleTemplateSelected = (template: DeploymentTemplate) => {
    setSelectedTemplate(template)

    // If template has variables, show variable input dialog
    if (template.variables && Object.keys(template.variables).length > 0) {
      setShowVariableInput(true)
    } else {
      // No variables, apply template directly
      applyTemplateToForm(template.template_definition as DeploymentDefinition)
    }
  }

  // Handle variable submission
  const handleVariablesSubmitted = async (values: Record<string, any>) => {
    if (!selectedTemplate) return

    try {
      // Render template with variables
      const rendered = await renderTemplate.mutateAsync({
        templateId: selectedTemplate.id,
        values,
      })

      // Apply rendered definition to form
      applyTemplateToForm(rendered as DeploymentDefinition)
      setShowVariableInput(false)
    } catch (error: any) {
      console.error('Failed to render template:', error)
      toast.error(`Failed to render template: ${error.message || 'Unknown error'}`)
    }
  }

  // Apply deployment definition to form fields
  const applyTemplateToForm = (definition: DeploymentDefinition) => {
    // Stack fields
    if (definition.compose_yaml) {
      setComposeYaml(definition.compose_yaml)
      setType('stack')  // Ensure type is set to stack
      return  // Stack templates only need compose_yaml
    }

    // Container fields
    if (definition.image) setImage(definition.image)
    if (definition.ports) setPorts(definition.ports.join(', '))
    if (definition.volumes) setVolumes(definition.volumes.join(', '))
    if (definition.environment) {
      const envString = Object.entries(definition.environment)
        .map(([key, value]) => `${key}=${value}`)
        .join('\n')
      setEnvironment(envString)
    }
    if (definition.labels) {
      const labelsString = Object.entries(definition.labels)
        .map(([key, value]) => `${key}=${value}`)
        .join('\n')
      setLabels(labelsString)
    }
    if (definition.privileged !== undefined) setPrivileged(definition.privileged)
    if (definition.network_mode) setNetworkMode(definition.network_mode)
    if (definition.cap_add) setCapabilities(definition.cap_add.join(', '))
    if (definition.memory_limit) setMemoryLimit(definition.memory_limit)
    if (definition.cpu_limit) setCpuLimit(definition.cpu_limit)
    if (definition.restart_policy) setRestartPolicy(definition.restart_policy)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!validateForm()) {
      return
    }

    // For stacks, run format & validate (same as Format & Validate button)
    let yamlToUse = composeYaml
    if (type === 'stack' && configEditorRef.current) {
      // Try to format/auto-fix first
      const formatted = configEditorRef.current.format()
      if (formatted) {
        yamlToUse = formatted
      }
    }

    // Validate configuration before saving
    if (configEditorRef.current) {
      const validation = configEditorRef.current.validate()
      if (!validation.valid) {
        const fieldName = type === 'stack' ? 'compose_yaml' : 'definition'
        const errorMessage = type === 'stack'
          ? 'Invalid YAML format. Please fix errors before saving.'
          : 'Invalid JSON format. Please fix errors before saving.'
        setErrors({
          ...errors,
          [fieldName]: validation.error || errorMessage,
        })
        return
      }
    }

    try {
      // Build deployment definition
      let definition: DeploymentDefinition

      if (type === 'stack') {
        // For stacks, the definition is the YAML string
        definition = {
          compose_yaml: yamlToUse.trim(),
        }
      } else {
        // For containers, build from form fields
        definition = {
          image: image.trim(),
          name: name.trim(),
        }

      // Add optional fields
      if (ports) {
        definition.ports = ports.split(',').map(p => p.trim()).filter(Boolean)
      }

      if (volumes) {
        definition.volumes = volumes.split(',').map(v => v.trim()).filter(Boolean)
      }

      if (environment) {
        const envVars: Record<string, string> = {}
        environment.split('\n').forEach(line => {
          const [key, ...valueParts] = line.split('=')
          if (key && valueParts.length > 0) {
            envVars[key.trim()] = valueParts.join('=').trim()
          }
        })
        if (Object.keys(envVars).length > 0) {
          definition.environment = envVars
        }
      }

      if (labels) {
        const labelMap: Record<string, string> = {}
        labels.split('\n').forEach(line => {
          const [key, ...valueParts] = line.split('=')
          if (key && valueParts.length > 0) {
            labelMap[key.trim()] = valueParts.join('=').trim()
          }
        })
        if (Object.keys(labelMap).length > 0) {
          definition.labels = labelMap
        }
      }

      if (privileged) {
        definition.privileged = true
      }

      if (networkMode !== 'bridge') {
        definition.network_mode = networkMode
      }

      if (capabilities) {
        definition.cap_add = capabilities.split(',').map(c => c.trim()).filter(Boolean)
      }

      if (memoryLimit) {
        definition.memory_limit = memoryLimit
      }

      if (cpuLimit) {
        definition.cpu_limit = cpuLimit
      }

      if (restartPolicy !== 'unless-stopped') {
        definition.restart_policy = restartPolicy
      }
      }

      // Create or update deployment
      if (isEditMode && deployment) {
        // Update existing deployment (overwrites the existing one)
        await updateDeployment.mutateAsync({
          deploymentId: deployment.id,
          name: name.trim(),
          type,
          host_id: hostId,
          definition,
        })
        onClose()
      } else {
        // Create new deployment
        await createDeployment.mutateAsync({
          name: name.trim(),
          type,
          host_id: hostId,
          definition,
        })

        // If "Save as Template" is enabled, create template
        if (saveAsTemplate) {
          try {
            await createTemplate.mutateAsync({
              name: templateName.trim(),
              deployment_type: type,
              template_definition: definition,
              category: templateCategory.trim() || null,
              description: templateDescription.trim() || null,
            })
            toast.success('Deployment and template created successfully')
          } catch (templateError: any) {
            // Check if it's a duplicate name error
            if (templateError.message && templateError.message.includes('already exists')) {
              // Show inline error on template name field, don't close form
              setErrors(prev => ({
                ...prev,
                templateName: 'A template with this name already exists. Please choose a different name.',
              }))
              toast.error('Template name already exists')
              return // Don't close form - let user fix the error
            } else {
              // Other template error - deployment succeeded but template failed
              toast.warning(`Deployment created, but failed to save template: ${templateError.message}`)
            }
          }
        } else {
          // No template, just show deployment success
          toast.success('Deployment created successfully')
        }

        onClose()
      }
    } catch (error: any) {
      // Deployment creation failed - show error
      console.error(`Failed to ${isEditMode ? 'update' : 'create'} deployment:`, error)
      toast.error(`Failed to ${isEditMode ? 'update' : 'create'} deployment: ${error.message || 'Unknown error'}`)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto" data-testid="deployment-form">
        <DialogHeader>
          <DialogTitle>{isEditMode ? 'Edit Deployment' : 'New Deployment'}</DialogTitle>
          <DialogDescription>
            {isEditMode ? 'Modify deployment configuration before execution' : 'Deploy a container to your Docker host'}
          </DialogDescription>
        </DialogHeader>

        {/* Template Selection Button (hidden in edit mode) */}
        {!isEditMode && (
          <div className="flex justify-end -mt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setShowTemplateSelector(true)}
              data-testid="select-template"
              className="gap-2"
            >
              <Layers className="h-4 w-4" />
              From Template
            </Button>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Error Banner (when editing failed/rolled_back deployment) */}
          {isEditMode && deployment && (deployment.status === 'failed' || deployment.status === 'rolled_back') && deployment.error_message && (
            <div className="bg-destructive/10 border border-destructive rounded-lg p-4">
              <div className="flex gap-3">
                <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <h4 className="font-semibold text-destructive">Previous Deployment Failed</h4>
                  <p className="text-sm text-destructive/80 mt-1">{deployment.error_message}</p>
                  <p className="text-xs text-muted-foreground mt-2">Edit the configuration below to fix the issue and retry.</p>
                </div>
              </div>
            </div>
          )}

          {/* Basic Information */}
          <div className="space-y-4">
            <h3 className="text-lg font-semibold">Basic Information</h3>

            {/* Deployment Name */}
            <div className="space-y-2">
              <Label htmlFor="name">Deployment Name *</Label>
              <Input
                id="name"
                name="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-web-server"
                className={errors.name ? 'border-destructive' : ''}
              />
              {errors.name && (
                <p className="text-sm text-destructive">{errors.name}</p>
              )}
            </div>

            {/* Deployment Type */}
            <div className="space-y-2">
              <Label htmlFor="type">Deployment Type</Label>
              <Select value={type} onValueChange={(value) => setType(value as DeploymentType)}>
                <SelectTrigger id="type">
                  <SelectValue placeholder="Select deployment type">
                    {type === 'container' ? 'Container' : 'Docker Compose Stack'}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="container">Container</SelectItem>
                  <SelectItem value="stack">Docker Compose Stack</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {type === 'container' ? (
                  <>
                    <strong>Container:</strong> Deploy a single service (e.g., Nginx, Radarr, PostgreSQL).
                    Specify image, ports, and environment variables below.
                  </>
                ) : (
                  <>
                    <strong>Stack:</strong> Deploy multiple services with Docker Compose (e.g., WordPress + MySQL + Redis).
                    Provide a complete Compose YAML file with 'services' section.
                  </>
                )}
              </p>
            </div>

            {/* Host Selection */}
            <div className="space-y-2">
              <Label htmlFor="host">Target Host *</Label>
              <Select value={hostId} onValueChange={setHostId}>
                <SelectTrigger id="host" className={errors.hostId ? 'border-destructive' : ''}>
                  <SelectValue>
                    {hosts.find(h => h.id === hostId)?.name || 'Select a host'}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {[...hosts].sort((a, b) => a.name.localeCompare(b.name)).map((host) => (
                    <SelectItem key={host.id} value={host.id}>
                      {host.name || host.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.hostId && (
                <p className="text-sm text-destructive">{errors.hostId}</p>
              )}
            </div>
          </div>

          {/* Stack Configuration */}
          {type === 'stack' && (
            <div className="space-y-4">
              <h3 className="text-lg font-semibold">Docker Compose Configuration</h3>

              {/* Compose YAML */}
              <div className="space-y-2">
                <Label htmlFor="compose_yaml">Docker Compose YAML *</Label>
                <ConfigurationEditor
                  ref={configEditorRef}
                  type="stack"
                  value={composeYaml}
                  onChange={setComposeYaml}
                  error={errors.compose_yaml}
                  rows={15}
                />
              </div>
            </div>
          )}

          {/* Container Configuration */}
          {type === 'container' && (
            <div className="space-y-4">
              <h3 className="text-lg font-semibold">Container Configuration</h3>

              {/* Image */}
              <div className="space-y-2">
                <Label htmlFor="image">Docker Image *</Label>
                <Input
                  id="image"
                  name="image"
                  value={image}
                  onChange={(e) => setImage(e.target.value)}
                  placeholder="nginx:latest"
                  className={errors.image ? 'border-destructive' : ''}
                />
                {errors.image && (
                  <p className="text-sm text-destructive">{errors.image}</p>
                )}
              </div>

              {/* Ports */}
              <div className="space-y-2">
                <Label htmlFor="ports">Port Mappings</Label>
                <Input
                  id="ports"
                  name="ports"
                  value={ports}
                  onChange={(e) => setPorts(e.target.value)}
                  placeholder="8080:80, 443:443"
                  className={errors.ports ? 'border-destructive' : ''}
                />
                <p className="text-xs text-muted-foreground">
                  Format: host_port:container_port (comma-separated)
                </p>
                {errors.ports && (
                  <p className="text-sm text-destructive">{errors.ports}</p>
                )}
              </div>

              {/* Volumes */}
              <div className="space-y-2">
                <Label htmlFor="volumes">Volume Mounts</Label>
                <Input
                  id="volumes"
                  name="volumes"
                  value={volumes}
                  onChange={(e) => setVolumes(e.target.value)}
                  placeholder="/host/path:/container/path"
                  className={errors.volumes ? 'border-destructive' : ''}
                />
                <p className="text-xs text-muted-foreground">
                  Format: host_path:container_path (comma-separated)
                </p>
                {errors.volumes && (
                  <p className="text-sm text-destructive">{errors.volumes}</p>
                )}
              </div>

              {/* Environment Variables */}
              <div className="space-y-2">
                <Label htmlFor="environment">Environment Variables</Label>
                <Textarea
                  id="environment"
                  name="environment"
                  value={environment}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setEnvironment(e.target.value)}
                  placeholder="VAR1=value1&#10;VAR2=value2"
                  rows={4}
                />
                <p className="text-xs text-muted-foreground">
                  One per line: KEY=value
                </p>
              </div>

              {/* Network Mode */}
              <div className="space-y-2">
                <Label htmlFor="network">Network Mode</Label>
                <Select value={networkMode} onValueChange={setNetworkMode}>
                  <SelectTrigger id="network">
                    <SelectValue>
                      {networkMode === 'bridge' ? 'Bridge (default)' : networkMode === 'host' ? 'Host' : 'None'}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bridge">Bridge (default)</SelectItem>
                    <SelectItem value="host">Host</SelectItem>
                    <SelectItem value="none">None</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Restart Policy */}
              <div className="space-y-2">
                <Label htmlFor="restart">Restart Policy</Label>
                <Select value={restartPolicy} onValueChange={setRestartPolicy}>
                  <SelectTrigger id="restart">
                    <SelectValue>
                      {restartPolicy === 'no' ? 'No' : restartPolicy === 'always' ? 'Always' : restartPolicy === 'unless-stopped' ? 'Unless Stopped' : 'On Failure'}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="no">No</SelectItem>
                    <SelectItem value="always">Always</SelectItem>
                    <SelectItem value="unless-stopped">Unless Stopped</SelectItem>
                    <SelectItem value="on-failure">On Failure</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          {/* Security Warnings */}
          {securityWarnings.length > 0 && (
            <div className="rounded-lg border border-yellow-500/50 bg-yellow-500/10 p-4 space-y-2">
              <div className="flex items-center gap-2 font-semibold text-yellow-700 dark:text-yellow-500">
                <AlertTriangle className="h-5 w-5" />
                Security Warnings
              </div>
              <ul className="list-disc list-inside space-y-1 text-sm text-yellow-700 dark:text-yellow-500">
                {securityWarnings.map((warning, i) => (
                  <li key={i}>{warning}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Save as Template Section (only in create mode) */}
          {!isEditMode && (
            <div className="space-y-4 pt-6 border-t">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="saveAsTemplate"
                  checked={saveAsTemplate}
                  onChange={(e) => setSaveAsTemplate(e.target.checked)}
                  className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0"
                />
                <Label htmlFor="saveAsTemplate" className="cursor-pointer">
                  Save as Template
                </Label>
              </div>

              {saveAsTemplate && (
                <div className="space-y-4 pl-6">
                  <p className="text-sm text-muted-foreground">
                    Save this configuration as a reusable template for future deployments
                  </p>

                  <div className="space-y-2">
                    <Label htmlFor="templateName">Template Name *</Label>
                    <Input
                      id="templateName"
                      value={templateName}
                      onChange={(e) => setTemplateName(e.target.value)}
                      placeholder="e.g., Nginx Reverse Proxy"
                      className={errors.templateName ? 'border-destructive' : ''}
                    />
                    {errors.templateName && (
                      <p className="text-sm text-destructive">{errors.templateName}</p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="templateCategory">Category (optional)</Label>
                    <Input
                      id="templateCategory"
                      value={templateCategory}
                      onChange={(e) => setTemplateCategory(e.target.value)}
                      placeholder="e.g., Web Servers, Databases"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="templateDescription">Description (optional)</Label>
                    <Textarea
                      id="templateDescription"
                      value={templateDescription}
                      onChange={(e) => setTemplateDescription(e.target.value)}
                      placeholder="Describe what this template does..."
                      rows={3}
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Form Actions */}
          <div className="flex items-center justify-end gap-3 pt-4 border-t">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={createDeployment.isPending || updateDeployment.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={createDeployment.isPending || updateDeployment.isPending}
              data-testid="create-deployment-submit"
            >
              {isEditMode
                ? (updateDeployment.isPending ? 'Saving...' : 'Save Changes')
                : (createDeployment.isPending ? 'Creating...' : 'Create Deployment')}
            </Button>
          </div>
        </form>
      </DialogContent>

      {/* Template Selector Dialog */}
      <TemplateSelector
        isOpen={showTemplateSelector}
        onClose={() => setShowTemplateSelector(false)}
        onSelect={handleTemplateSelected}
      />

      {/* Variable Input Dialog */}
      <VariableInputDialog
        isOpen={showVariableInput}
        onClose={() => setShowVariableInput(false)}
        onSubmit={handleVariablesSubmitted}
        template={selectedTemplate}
      />
    </Dialog>
  )
}
