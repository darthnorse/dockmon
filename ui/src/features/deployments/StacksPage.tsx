/**
 * Stacks Page (v2.2.8+)
 *
 * Two-column master-detail layout for managing Docker Compose stacks:
 * - Left panel: Searchable stack list with "New Stack" button
 * - Right panel: Stack editor for viewing/editing compose.yaml and .env
 *
 * All operations (edit, rename, clone, delete, deploy) happen inline.
 */

import { useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { useStacks } from './hooks/useStacks'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import { StackListPanel } from './components/StackListPanel'
import { StackEditor } from './components/StackEditor'
import { ImportStackModal } from './components/ImportStackModal'

export function StacksPage() {
  const [selectedStackName, setSelectedStackName] = useState<string | null>(null)
  const [showImportModal, setShowImportModal] = useState(false)

  const { data: stacks, isLoading, error } = useStacks()
  const { data: hosts } = useHosts()

  // Handle stack selection from list panel
  const handleStackSelect = (name: string) => {
    setSelectedStackName(name)
  }

  // Handle stack changes from editor (after create, rename, delete)
  const handleStackChange = (name: string | null) => {
    setSelectedStackName(name)
  }

  // Error state - show full page error
  if (error) {
    return (
      <div className="p-3 sm:p-4 md:p-6 pt-16 md:pt-6">
        <div className="flex items-center gap-2 p-4 bg-destructive/10 text-destructive rounded-lg">
          <AlertCircle className="h-5 w-5" />
          <p>Failed to load stacks: {error.message}</p>
        </div>
      </div>
    )
  }

  const hostsList = (hosts || []).map((h) => ({ id: h.id, name: h.name || h.id }))
  const isCreateMode = selectedStackName === '__new__'

  // Find the selected stack to get deployed_to info
  const selectedStack = stacks?.find((s) => s.name === selectedStackName)

  return (
    <div className="h-screen flex flex-col pt-14 md:pt-0">
      {/* Two-column layout - fills entire screen */}
      <div className="flex-1 min-h-0 grid grid-cols-[280px_1fr]">
        {/* Left panel: Stack list */}
        <div className="border-r bg-muted/30 overflow-hidden">
          <StackListPanel
            stacks={stacks}
            isLoading={isLoading}
            selectedStackName={selectedStackName}
            isCreateMode={isCreateMode}
            onStackSelect={handleStackSelect}
            onImport={() => setShowImportModal(true)}
          />
        </div>

        {/* Right panel: Stack editor */}
        <div className="p-6 overflow-hidden">
          <StackEditor
            selectedStackName={selectedStackName}
            hosts={hostsList}
            deployedTo={selectedStack?.deployed_to}
            onStackChange={handleStackChange}
          />
        </div>
      </div>

      {/* Import Stack Modal */}
      <ImportStackModal
        isOpen={showImportModal}
        onClose={() => setShowImportModal(false)}
      />
    </div>
  )
}
