/**
 * Agent Registration Component for DockMon v2.2.0
 *
 * Allows users to generate registration tokens and display installation commands
 */

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Copy, Check, Terminal } from 'lucide-react'
import { useGenerateToken } from '../hooks/useAgents'

export function AgentRegistration() {
  const [copied, setCopied] = useState(false)
  const generateToken = useGenerateToken()

  const token = generateToken.data?.token
  const expiresAt = generateToken.data?.expires_at

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const installCommand = token
    ? `docker run -d \\
  --name dockmon-agent \\
  --restart unless-stopped \\
  -v /var/run/docker.sock:/var/run/docker.sock:ro \\
  -e DOCKMON_URL=http://YOUR_DOCKMON_HOST:8080 \\
  -e REGISTRATION_TOKEN=${token} \\
  ghcr.io/darthnorse/dockmon-agent:latest`
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
                  onClick={() => handleCopy(token)}
                >
                  {copied ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Installation Command</label>
              <div className="relative">
                <pre className="rounded bg-muted p-4 text-sm font-mono overflow-x-auto">
                  {installCommand}
                </pre>
                <Button
                  size="sm"
                  variant="outline"
                  className="absolute top-2 right-2"
                  onClick={() => handleCopy(installCommand)}
                >
                  {copied ? (
                    <Check className="h-4 w-4 mr-1" />
                  ) : (
                    <Copy className="h-4 w-4 mr-1" />
                  )}
                  Copy
                </Button>
              </div>
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
