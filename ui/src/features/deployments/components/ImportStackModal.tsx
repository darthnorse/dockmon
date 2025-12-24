/**
 * Import Stack Modal
 *
 * Allows users to import an existing Docker Compose stack into DockMon.
 * Auto-detects which host(s) have the stack running.
 *
 * Two import methods:
 * 1. Paste/Upload - User provides compose YAML content directly
 * 2. Browse Host - Scan agent host directories for compose files (Phase 3)
 *
 * Flow:
 * 1. User selects import method (tabs)
 * 2. For paste: User pastes/uploads compose YAML
 * 3. For browse: User selects host, scans directories, picks a compose file
 * 4. If compose has 'name:' field -> auto-detect hosts and import
 * 5. If no 'name:' field -> show dropdown of known stacks from container labels
 * 6. On success -> show which hosts got deployment records
 */

import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { apiClient } from '@/lib/api/client'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
import { useImportDeployment, useScanComposeDirs, useReadComposeFile } from '../hooks/useDeployments'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import type {
  Deployment,
  KnownStack,
  ImportDeploymentRequest,
  ImportDeploymentResponse,
  ComposeFileInfo,
} from '../types'
import {
  CheckCircle2,
  Upload,
  FolderSearch,
  Loader2,
  FileCode,
} from 'lucide-react'
import { cn } from '@/lib/utils'

type ImportStep = 'input' | 'select-name' | 'success'
type ImportMethod = 'paste' | 'browse'

interface ImportStackModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess?: (deployments: Deployment[]) => void
}

export function ImportStackModal({
  isOpen,
  onClose,
  onSuccess,
}: ImportStackModalProps) {
  // Step and method state
  const [step, setStep] = useState<ImportStep>('input')
  const [method, setMethod] = useState<ImportMethod>('paste')

  // Paste/Upload state
  const [composeContent, setComposeContent] = useState('')
  const [envContent, setEnvContent] = useState('')
  const [showEnvField, setShowEnvField] = useState(false)

  // Browse host state
  const [selectedHostId, setSelectedHostId] = useState('')
  const [additionalPaths, setAdditionalPaths] = useState('')
  const [composeFiles, setComposeFiles] = useState<ComposeFileInfo[]>([])
  const [selectedFilePath, setSelectedFilePath] = useState('')

  // Common state
  const [selectedProjectName, setSelectedProjectName] = useState('')
  const [knownStacks, setKnownStacks] = useState<KnownStack[]>([])
  const [error, setError] = useState<string | null>(null)
  const [createdDeployments, setCreatedDeployments] = useState<Deployment[]>([])

  // Hooks
  const importDeployment = useImportDeployment()
  const scanComposeDirs = useScanComposeDirs()
  const readComposeFile = useReadComposeFile()
  const { data: hosts } = useHosts()

  // Filter to show hosts that support directory scanning (local + agent)
  // Remote/mTLS hosts don't have filesystem access
  const scannableHosts = hosts?.filter((h) =>
    h.connection_type === 'agent' || h.connection_type === 'local'
  ) || []

  // Get selected host info
  const selectedHost = scannableHosts.find((h) => h.id === selectedHostId)
  const isLocalHost = selectedHost?.connection_type === 'local'
  const isAgentHost = selectedHost?.connection_type === 'agent'

  // Fetch agent info when an agent host is selected (to check if containerized)
  const { data: agentInfo } = useQuery({
    queryKey: ['host-agent', selectedHostId],
    queryFn: () =>
      apiClient.get<{ is_container_mode: boolean }>(`/hosts/${selectedHostId}/agent`),
    enabled: !!selectedHostId && isAgentHost,
  })

  // Generate dynamic help text based on selected host
  const getScanHelpText = () => {
    if (!selectedHostId) {
      return 'Select a host to scan for compose files.'
    }
    if (isLocalHost) {
      return 'Scanning localhost. Mount paths like /opt or /srv into the DockMon container for scanning to work.'
    }
    if (isAgentHost) {
      if (agentInfo?.is_container_mode) {
        return 'Agent runs in a container. Mount paths into the agent container for scanning to work.'
      }
      return 'Agent runs as a system service. Filesystem scanning is available.'
    }
    return 'Select a host to scan for compose files.'
  }

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      setComposeContent(e.target?.result as string)
    }
    reader.readAsText(file)
  }

  const handleScanHost = async () => {
    if (!selectedHostId) {
      setError('Please select a host')
      return
    }

    setError(null)
    setComposeFiles([])
    setSelectedFilePath('')

    // Parse additional paths (comma or newline separated)
    const extraPaths = additionalPaths
      .split(/[,\n]/)
      .map((p) => p.trim())
      .filter((p) => p.length > 0)

    try {
      const scanParams: { hostId: string; request?: { paths: string[] } } = {
        hostId: selectedHostId,
      }
      if (extraPaths.length > 0) {
        scanParams.request = { paths: extraPaths }
      }
      const result = await scanComposeDirs.mutateAsync(scanParams)

      if (result.success) {
        setComposeFiles(result.compose_files)
        if (result.compose_files.length === 0) {
          setError('No compose files found in scanned directories')
        }
      } else {
        setError(result.error || 'Scan failed')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Scan failed'
      setError(message)
    }
  }

  const handleSelectComposeFile = async (path: string) => {
    setSelectedFilePath(path)
    setError(null)

    const file = composeFiles.find((f) => f.path === path)
    if (!file) return

    // Auto-fetch the compose file content
    try {
      const result = await readComposeFile.mutateAsync({
        hostId: selectedHostId,
        path: path,
      })

      if (result.success) {
        setComposeContent(result.content || '')
        if (result.env_content) {
          setEnvContent(result.env_content)
          setShowEnvField(true)
        }
      } else {
        setError(result.error || 'Failed to read file')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to read file'
      setError(message)
    }
  }

  const handleImport = async (projectName?: string) => {
    if (!composeContent.trim()) {
      setError('Please provide compose file content')
      return
    }

    setError(null)

    try {
      const request: ImportDeploymentRequest = {
        compose_content: composeContent,
      }
      if (envContent) {
        request.env_content = envContent
      }
      if (projectName) {
        request.project_name = projectName
      }
      const result: ImportDeploymentResponse =
        await importDeployment.mutateAsync(request)

      if (result.requires_name_selection) {
        // Compose file has no name: field - show selection UI
        setKnownStacks(result.known_stacks || [])
        setStep('select-name')
      } else if (result.success) {
        // Auto-detected and imported successfully
        setCreatedDeployments(result.deployments_created)
        setStep('success')
        onSuccess?.(result.deployments_created)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Import failed'
      setError(message)
    }
  }

  const handleSelectName = async () => {
    if (!selectedProjectName) {
      setError('Please select a stack name')
      return
    }
    await handleImport(selectedProjectName)
  }

  const handleClose = () => {
    // Reset form when closing
    resetForm()
    onClose()
  }

  const resetForm = () => {
    setStep('input')
    setMethod('paste')
    setComposeContent('')
    setEnvContent('')
    setShowEnvField(false)
    setSelectedHostId('')
    setAdditionalPaths('')
    setComposeFiles([])
    setSelectedFilePath('')
    setSelectedProjectName('')
    setKnownStacks([])
    setError(null)
    setCreatedDeployments([])
  }

  // Reset form when modal opens/closes
  useEffect(() => {
    if (!isOpen) {
      resetForm()
    }
  }, [isOpen])

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Import Existing Stack</DialogTitle>
          <DialogDescription>
            Import an existing Docker Compose stack into DockMon. DockMon will
            auto-detect which host(s) have the stack running.
          </DialogDescription>
        </DialogHeader>

        {step === 'input' && (
          <div className="space-y-4">
            {/* Method Toggle */}
            <div className="flex gap-2 p-1 bg-muted rounded-lg">
              <button
                onClick={() => setMethod('paste')}
                className={cn(
                  'flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                  method === 'paste'
                    ? 'bg-background shadow text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <Upload className="h-4 w-4" />
                Paste / Upload
              </button>
              <button
                onClick={() => setMethod('browse')}
                className={cn(
                  'flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                  method === 'browse'
                    ? 'bg-background shadow text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <FolderSearch className="h-4 w-4" />
                Browse Host
              </button>
            </div>

            {/* Paste/Upload Content */}
            {method === 'paste' && (
              <>
                {/* Compose Content */}
                <div>
                  <Label htmlFor="compose-content">Compose File</Label>
                  <div className="flex gap-2 mb-2">
                    <Button variant="outline" size="sm" asChild>
                      <label className="cursor-pointer">
                        <Upload className="h-4 w-4 mr-2" />
                        Upload File
                        <input
                          type="file"
                          accept=".yaml,.yml"
                          onChange={handleFileUpload}
                          className="hidden"
                        />
                      </label>
                    </Button>
                  </div>
                  <Textarea
                    id="compose-content"
                    value={composeContent}
                    onChange={(e) => setComposeContent(e.target.value)}
                    placeholder="Paste your docker-compose.yml content here..."
                    className="font-mono text-sm h-48"
                  />
                </div>

                {/* Optional .env Content */}
                <div>
                  {!showEnvField ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowEnvField(true)}
                      className="text-muted-foreground"
                    >
                      + Add .env content (optional)
                    </Button>
                  ) : (
                    <>
                      <Label htmlFor="env-content">
                        .env Content (optional)
                      </Label>
                      <Textarea
                        id="env-content"
                        value={envContent}
                        onChange={(e) => setEnvContent(e.target.value)}
                        placeholder="KEY=value"
                        className="font-mono text-sm h-24"
                      />
                    </>
                  )}
                </div>
              </>
            )}

            {/* Browse Host Content */}
            {method === 'browse' && (
              <>
                {/* Host Selection */}
                <div>
                  <Label htmlFor="host-select">Select Agent Host</Label>
                  <Select
                    value={selectedHostId}
                    onValueChange={setSelectedHostId}
                  >
                    <SelectTrigger id="host-select">
                      <SelectValue placeholder="Select a host to scan...">
                        {selectedHostId
                          ? scannableHosts.find((h) => h.id === selectedHostId)?.name || selectedHostId
                          : 'Select a host to scan...'}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {scannableHosts.length === 0 ? (
                        <div className="p-2 text-sm text-muted-foreground">
                          No agent hosts available
                        </div>
                      ) : (
                        scannableHosts.map((host) => (
                          <SelectItem key={host.id} value={host.id}>
                            {host.name || host.id}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                </div>

                {/* Additional Paths (optional) */}
                <div>
                  <Label htmlFor="additional-paths">
                    Additional Paths (optional)
                  </Label>
                  <Input
                    id="additional-paths"
                    value={additionalPaths}
                    onChange={(e) => setAdditionalPaths(e.target.value)}
                    placeholder="/custom/path, /another/path"
                    className="font-mono text-sm"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Comma-separated paths to scan in addition to defaults
                  </p>
                </div>

                {/* Scan Button */}
                <Button
                  onClick={handleScanHost}
                  disabled={!selectedHostId || scanComposeDirs.isPending}
                  className="w-full gap-2"
                >
                  {scanComposeDirs.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Scanning...
                    </>
                  ) : (
                    <>
                      <FolderSearch className="h-4 w-4" />
                      Scan for Compose Files
                    </>
                  )}
                </Button>

                {scannableHosts.length === 0 ? (
                  <Alert>
                    <AlertDescription>
                      Directory scanning requires an agent-based host. No agent
                      hosts are currently connected. Use the Paste/Upload tab to
                      import manually.
                    </AlertDescription>
                  </Alert>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {getScanHelpText()}
                  </p>
                )}

                {/* Compose Files List */}
                {composeFiles.length > 0 && (
                  <div>
                    <Label>Discovered Compose Files</Label>
                    <div className="border rounded-md divide-y max-h-64 overflow-y-auto mt-2">
                      {composeFiles.map((file) => (
                        <button
                          key={file.path}
                          onClick={() => handleSelectComposeFile(file.path)}
                          disabled={readComposeFile.isPending}
                          className={cn(
                            'w-full p-3 text-left hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
                            selectedFilePath === file.path ? 'bg-muted' : ''
                          )}
                        >
                          <div className="flex items-start gap-3">
                            {readComposeFile.isPending && selectedFilePath === file.path ? (
                              <Loader2 className="h-5 w-5 text-muted-foreground mt-0.5 shrink-0 animate-spin" />
                            ) : (
                              <FileCode className="h-5 w-5 text-muted-foreground mt-0.5 shrink-0" />
                            )}
                            <div className="min-w-0 flex-1">
                              <div className="font-medium text-sm truncate">
                                {file.project_name}
                              </div>
                              <div className="text-xs text-muted-foreground truncate">
                                {file.path}
                              </div>
                              <div className="text-xs text-muted-foreground mt-1">
                                {file.services.length} service(s):{' '}
                                {file.services.slice(0, 3).join(', ')}
                                {file.services.length > 3 && '...'}
                              </div>
                            </div>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Compose Content for selected file */}
                {selectedFilePath && composeContent && (
                  <div>
                    <Label htmlFor="browse-compose-content">
                      Compose File Content
                    </Label>
                    <Textarea
                      id="browse-compose-content"
                      value={composeContent}
                      onChange={(e) => setComposeContent(e.target.value)}
                      placeholder="Compose file content..."
                      className="font-mono text-sm h-32"
                    />
                  </div>
                )}
              </>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={handleClose}
                disabled={importDeployment.isPending}
              >
                Cancel
              </Button>
              <Button
                onClick={() => handleImport()}
                disabled={importDeployment.isPending || !composeContent.trim()}
              >
                {importDeployment.isPending ? 'Importing...' : 'Import Stack'}
              </Button>
            </DialogFooter>
          </div>
        )}

        {step === 'select-name' && (
          <div className="space-y-4">
            <Alert>
              <AlertDescription>
                The compose file doesn&apos;t have a{' '}
                <code className="bg-muted px-1 rounded">name:</code> field.
                Please select which stack this compose file belongs to:
              </AlertDescription>
            </Alert>

            <div>
              <Label htmlFor="stack-select">Select Stack</Label>
              <Select
                value={selectedProjectName}
                onValueChange={setSelectedProjectName}
              >
                <SelectTrigger id="stack-select">
                  <SelectValue placeholder="Select a stack..." />
                </SelectTrigger>
                <SelectContent>
                  {knownStacks.map((stack) => (
                    <SelectItem key={stack.name} value={stack.name}>
                      <div className="flex flex-col items-start">
                        <span className="font-medium">{stack.name}</span>
                        <span className="text-xs text-muted-foreground">
                          {stack.container_count} container(s) on{' '}
                          {stack.host_names.join(', ')}
                        </span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {knownStacks.length === 0 && (
              <Alert>
                <AlertDescription>
                  No stacks found. Make sure you have Docker Compose stacks
                  running that were deployed with the standard compose labels.
                </AlertDescription>
              </Alert>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setStep('input')}
                disabled={importDeployment.isPending}
              >
                Back
              </Button>
              <Button
                onClick={handleSelectName}
                disabled={importDeployment.isPending || !selectedProjectName}
              >
                {importDeployment.isPending ? 'Importing...' : 'Import Stack'}
              </Button>
            </DialogFooter>
          </div>
        )}

        {step === 'success' && (
          <div className="space-y-4">
            <Alert className="border-green-500 bg-green-50 dark:bg-green-950">
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              <AlertDescription className="text-green-800 dark:text-green-200">
                Successfully imported stack to {createdDeployments.length}{' '}
                host(s)
              </AlertDescription>
            </Alert>

            <ul className="list-disc list-inside space-y-1">
              {createdDeployments.map((d) => (
                <li key={d.id}>
                  <span className="font-medium">{d.name}</span> on{' '}
                  {d.host_name || d.host_id}
                </li>
              ))}
            </ul>

            <DialogFooter>
              <Button onClick={handleClose}>Done</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
