/**
 * Display New API Key Modal
 * Shows the newly created API key with copy-to-clipboard and usage examples
 */

import { useState } from 'react'
import { Copy, Check, Code, Terminal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CreateApiKeyResponse } from '@/types/api-keys'

interface DisplayNewKeyModalProps {
  isOpen: boolean
  onClose: () => void
  keyData: CreateApiKeyResponse
  onCopy: () => void
}

export function DisplayNewKeyModal({ isOpen, onClose, keyData, onCopy }: DisplayNewKeyModalProps) {
  const [copied, setCopied] = useState(false)
  const [selectedTab, setSelectedTab] = useState<'copy' | 'curl' | 'python'>('copy')

  if (!isOpen) return null

  const handleCopy = () => {
    onCopy()
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // Use actual hostname and port from browser
  const baseUrl = `${window.location.protocol}//${window.location.host}`

  const curlExample = `curl -k -H "Authorization: Bearer ${keyData.key}" \\
  ${baseUrl}/api/hosts`

  const pythonExample = `import requests

headers = {"Authorization": f"Bearer ${keyData.key}"}
response = requests.get("${baseUrl}/api/hosts", headers=headers, verify=False)
print(response.json())`

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-900 rounded-lg max-w-2xl w-full mx-4 border border-gray-800 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-gray-900 border-b border-gray-800 px-6 py-4">
          <h2 className="text-lg font-semibold text-white">API Key Created Successfully</h2>
          <p className="text-sm text-gray-400 mt-1">Save this key now - it will not be shown again!</p>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Key Display */}
          <div className="rounded-lg border border-green-900/30 bg-green-900/10 p-4">
            <p className="text-sm text-green-300 font-medium mb-3">Your API Key</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-gray-800 text-green-400 px-3 py-2 rounded text-sm font-mono break-all">
                {keyData.key}
              </code>
              <button
                onClick={handleCopy}
                className={`p-2 rounded transition-colors ${
                  copied
                    ? 'bg-green-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300'
                }`}
              >
                {copied ? <Check className="h-5 w-5" /> : <Copy className="h-5 w-5" />}
              </button>
            </div>
          </div>

          {/* Key Details */}
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="rounded border border-gray-800 bg-gray-800/30 p-3">
              <p className="text-gray-400 text-xs mb-1">Name</p>
              <p className="text-white font-medium">{keyData.name}</p>
            </div>
            <div className="rounded border border-gray-800 bg-gray-800/30 p-3">
              <p className="text-gray-400 text-xs mb-1">Scopes</p>
              <p className="text-white font-medium">{keyData.scopes}</p>
            </div>
            {keyData.expires_at && (
              <div className="rounded border border-gray-800 bg-gray-800/30 p-3">
                <p className="text-gray-400 text-xs mb-1">Expires</p>
                <p className="text-white font-medium">{new Date(keyData.expires_at).toLocaleDateString()}</p>
              </div>
            )}
          </div>

          {/* Usage Examples */}
          <div>
            <h3 className="text-sm font-semibold text-white mb-3">Usage Examples</h3>

            {/* Tabs */}
            <div className="flex gap-1 mb-3 border-b border-gray-800">
              {[
                { id: 'copy' as const, label: 'Copy Key', icon: Copy },
                { id: 'curl' as const, label: 'cURL', icon: Terminal },
                { id: 'python' as const, label: 'Python', icon: Code },
              ].map((tab) => {
                const Icon = tab.icon
                return (
                  <button
                    key={tab.id}
                    onClick={() => setSelectedTab(tab.id)}
                    className={`flex items-center gap-2 px-3 py-2 text-sm border-b-2 transition-colors ${
                      selectedTab === tab.id
                        ? 'border-blue-500 text-blue-400'
                        : 'border-transparent text-gray-400 hover:text-gray-300'
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    {tab.label}
                  </button>
                )
              })}
            </div>

            {/* Tab Content */}
            {selectedTab === 'copy' && (
              <div className="space-y-3 text-sm">
                <div className="p-3 rounded bg-gray-800/50 border border-gray-700">
                  <p className="text-gray-300 mb-2">Store the API key in an environment variable:</p>
                  <code className="text-green-400 text-xs">
                    export DOCKMON_API_KEY="{keyData.key}"
                  </code>
                </div>
                <p className="text-gray-400">Use it in your scripts and automation tools.</p>
              </div>
            )}

            {selectedTab === 'curl' && (
              <div className="space-y-2">
                <div className="p-3 rounded bg-gray-800 font-mono text-xs text-green-400 overflow-x-auto">
                  {curlExample}
                </div>
                <p className="text-xs text-gray-400">
                  Copy the API key to the Authorization header with "Bearer " prefix.
                </p>
              </div>
            )}

            {selectedTab === 'python' && (
              <div className="space-y-2">
                <div className="p-3 rounded bg-gray-800 font-mono text-xs text-blue-400 overflow-x-auto">
                  {pythonExample}
                </div>
              </div>
            )}
          </div>

          {/* Security Warning */}
          <div className="rounded bg-red-900/20 border border-red-900/30 p-3">
            <p className="text-xs text-red-300">
              <strong>Security:</strong> Keep this key secure! Anyone with the key can access DockMon with the granted
              permissions. Do not commit it to version control.
            </p>
          </div>

          {/* Action */}
          <div className="pt-4">
            <Button onClick={onClose} className="w-full">
              Got it - I've saved the key
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
