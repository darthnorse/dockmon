/**
 * Agent Registration Component for DockMon v2.2.0
 *
 * Allows users to generate registration tokens and display installation commands
 * Supports both Docker container and system service deployment options
 */

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Copy, Check, Terminal, Container, Server } from 'lucide-react'
import { useGenerateToken } from '../hooks/useAgents'
import { cn } from '@/lib/utils'

type InstallMethod = 'docker' | 'systemd'

export function AgentRegistration() {
  const [copied, setCopied] = useState<string | null>(null)
  const [installMethod, setInstallMethod] = useState<InstallMethod>('docker')
  const generateToken = useGenerateToken()

  const token = generateToken.data?.token
  const expiresAt = generateToken.data?.expires_at

  const handleCopy = async (text: string, id: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(id)
    setTimeout(() => setCopied(null), 2000)
  }

  const dockerCommand = token
    ? `docker run -d \\
  --name dockmon-agent \\
  --restart unless-stopped \\
  -v /var/run/docker.sock:/var/run/docker.sock:ro \\
  -e DOCKMON_URL=https://YOUR_DOCKMON_HOST \\
  -e REGISTRATION_TOKEN=${token} \\
  ghcr.io/darthnorse/dockmon-agent:latest`
    : ''

  const systemdInstallCommand = token
    ? `curl -fsSL https://raw.githubusercontent.com/darthnorse/dockmon/main/scripts/install-agent.sh | \\
  sudo DOCKMON_URL=https://YOUR_DOCKMON_HOST \\
  REGISTRATION_TOKEN=${token} bash`
    : ''

  const formatExpiry = (isoString: string) => {
    const date = new Date(isoString)
    const now = new Date()
    const diff = date.getTime() - now.getTime()
    const minutes = Math.floor(diff / 60000)
    return `${minutes} minute${minutes !== 1 ? 's' : ''}`
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Register New Agent</CardTitle>
        <CardDescription>
          Generate a registration token to install the DockMon agent on a remote Docker host
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!token ? (
          <>
            <p className="text-sm text-muted-foreground">
              Click the button below to generate a single-use registration token.
              The token expires after 15 minutes.
            </p>
            <Button
              onClick={() => generateToken.mutate()}
              disabled={generateToken.isPending}
            >
              {generateToken.isPending ? 'Generating...' : 'Generate Token'}
            </Button>
          </>
        ) : (
          <div className="space-y-4">
            <Alert>
              <Terminal className="h-4 w-4" />
              <AlertDescription>
                Token generated! Expires in{' '}
                <strong>{expiresAt && formatExpiry(expiresAt)}</strong>
              </AlertDescription>
            </Alert>

            <div className="space-y-2">
              <label className="text-sm font-medium">Registration Token</label>
              <div className="flex gap-2">
                <code className="flex-1 rounded bg-muted px-3 py-2 text-sm font-mono break-all">
                  {token}
                </code>
                <Button
                  size="icon"
                  variant="outline"
                  onClick={() => handleCopy(token, 'token')}
                >
                  {copied === 'token' ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>

            {/* Installation Method Tabs */}
            <div className="space-y-4">
              <div className="flex rounded-lg bg-muted p-1">
                <button
                  onClick={() => setInstallMethod('docker')}
                  className={cn(
                    'flex-1 flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                    installMethod === 'docker'
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <Container className="h-4 w-4" />
                  Docker Container
                </button>
                <button
                  onClick={() => setInstallMethod('systemd')}
                  className={cn(
                    'flex-1 flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                    installMethod === 'systemd'
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <Server className="h-4 w-4" />
                  System Service
                </button>
              </div>

              {installMethod === 'docker' && (
                <div className="space-y-2">
                  <label className="text-sm font-medium">Docker Run Command</label>
                  <div className="relative">
                    <pre className="rounded bg-muted p-4 text-sm font-mono overflow-x-auto whitespace-pre-wrap">
                      {dockerCommand}
                    </pre>
                    <Button
                      size="sm"
                      variant="outline"
                      className="absolute top-2 right-2"
                      onClick={() => handleCopy(dockerCommand, 'docker')}
                    >
                      {copied === 'docker' ? (
                        <Check className="h-4 w-4 mr-1" />
                      ) : (
                        <Copy className="h-4 w-4 mr-1" />
                      )}
                      Copy
                    </Button>
                  </div>
                </div>
              )}

              {installMethod === 'systemd' && (
                <div className="space-y-2">
                  <label className="text-sm font-medium">Install Command</label>
                  <p className="text-xs text-muted-foreground">
                    Run this command on your remote host to install the agent as a systemd service:
                  </p>
                  <div className="relative">
                    <pre className="rounded bg-muted p-4 text-sm font-mono overflow-x-auto whitespace-pre-wrap">
                      {systemdInstallCommand}
                    </pre>
                    <Button
                      size="sm"
                      variant="outline"
                      className="absolute top-2 right-2"
                      onClick={() => handleCopy(systemdInstallCommand, 'systemd')}
                    >
                      {copied === 'systemd' ? (
                        <Check className="h-4 w-4 mr-1" />
                      ) : (
                        <Copy className="h-4 w-4 mr-1" />
                      )}
                      Copy
                    </Button>
                  </div>
                </div>
              )}
            </div>

            <Alert>
              <AlertDescription className="text-sm">
                <strong>Note:</strong> Replace <code>YOUR_DOCKMON_HOST</code> with your DockMon
                server's hostname or IP address. The agent will connect via WebSocket to register.
              </AlertDescription>
            </Alert>

            <Button
              variant="outline"
              onClick={() => generateToken.reset()}
            >
              Generate New Token
            </Button>
          </div>
        )}

        {generateToken.isError && (
          <Alert variant="destructive">
            <AlertDescription>
              {generateToken.error?.message || 'Failed to generate token'}
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}
