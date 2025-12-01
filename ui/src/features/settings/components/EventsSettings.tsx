/**
 * Events Settings Component
 * Configure event suppression patterns to filter out noisy container events
 */

import { useState, useEffect } from 'react'
import { useGlobalSettings, useUpdateGlobalSettings } from '@/hooks/useSettings'
import { toast } from 'sonner'
import { X, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function EventsSettings() {
  const { data: settings } = useGlobalSettings()
  const updateSettings = useUpdateGlobalSettings()

  const [patterns, setPatterns] = useState<string[]>([])
  const [newPattern, setNewPattern] = useState('')
  const [isUpdating, setIsUpdating] = useState(false)

  // Sync state when settings load from API
  useEffect(() => {
    if (settings) {
      setPatterns(settings.event_suppression_patterns ?? [])
    }
  }, [settings])

  const handleAddPattern = async () => {
    const trimmedPattern = newPattern.trim()

    // Validation
    if (!trimmedPattern) {
      toast.error('Pattern cannot be empty')
      return
    }

    if (patterns.includes(trimmedPattern)) {
      toast.error('Pattern already exists')
      return
    }

    // Must contain at least one wildcard or be a valid container name
    if (trimmedPattern.length < 2) {
      toast.error('Pattern must be at least 2 characters')
      return
    }

    setIsUpdating(true)
    try {
      const updatedPatterns = [...patterns, trimmedPattern]
      await updateSettings.mutateAsync({ event_suppression_patterns: updatedPatterns })
      setPatterns(updatedPatterns)
      setNewPattern('')
      toast.success(`Pattern "${trimmedPattern}" added`)
    } catch (error) {
      toast.error('Failed to add pattern')
    } finally {
      setIsUpdating(false)
    }
  }

  const handleRemovePattern = async (patternToRemove: string) => {
    setIsUpdating(true)
    try {
      const updatedPatterns = patterns.filter(p => p !== patternToRemove)
      await updateSettings.mutateAsync({ event_suppression_patterns: updatedPatterns })
      setPatterns(updatedPatterns)
      toast.success(`Pattern "${patternToRemove}" removed`)
    } catch (error) {
      toast.error('Failed to remove pattern')
    } finally {
      setIsUpdating(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !isUpdating) {
      e.preventDefault()
      handleAddPattern()
    }
  }

  return (
    <div className="space-y-6">
      {/* Event Suppression */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Event Suppression</h3>
          <p className="text-xs text-gray-400 mt-1">
            Suppress events from containers matching these patterns. Events from matching containers
            will not be logged to the database, reducing noise from temporary or cronjob containers.
          </p>
        </div>

        <div className="space-y-4">
          {/* Pattern explanation */}
          <div className="rounded-md border border-gray-700 bg-gray-800/50 p-3">
            <p className="text-sm text-gray-300 mb-2">
              Use glob patterns with wildcards:
            </p>
            <ul className="text-xs text-gray-400 space-y-1 ml-4 list-disc">
              <li><code className="text-blue-400">runner-*</code> - matches containers starting with "runner-"</li>
              <li><code className="text-blue-400">*-tmp</code> - matches containers ending with "-tmp"</li>
              <li><code className="text-blue-400">*cronjob*</code> - matches containers containing "cronjob"</li>
            </ul>
          </div>

          {/* Current patterns */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Suppression Patterns ({patterns.length})
            </label>

            {patterns.length === 0 ? (
              <p className="text-sm text-gray-500 italic">No suppression patterns configured</p>
            ) : (
              <div className="flex flex-wrap gap-2 mb-3">
                {patterns.map((pattern) => (
                  <div
                    key={pattern}
                    className="flex items-center gap-1 rounded-md border border-gray-600 bg-gray-700 px-2 py-1"
                  >
                    <code className="text-sm text-gray-200">{pattern}</code>
                    <button
                      onClick={() => handleRemovePattern(pattern)}
                      disabled={isUpdating}
                      className="ml-1 text-gray-400 hover:text-red-400 disabled:opacity-50"
                      title="Remove pattern"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Add new pattern */}
          <div>
            <label htmlFor="new-pattern" className="block text-sm font-medium text-gray-300 mb-2">
              Add Pattern
            </label>
            <div className="flex gap-2">
              <input
                id="new-pattern"
                type="text"
                value={newPattern}
                onChange={(e) => setNewPattern(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="e.g., runner-* or *-cronjob-*"
                disabled={isUpdating}
                className="flex-1 rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              />
              <Button
                onClick={handleAddPattern}
                disabled={isUpdating || !newPattern.trim()}
                size="sm"
                className="flex items-center gap-1"
              >
                <Plus className="h-4 w-4" />
                Add
              </Button>
            </div>
            <p className="mt-1 text-xs text-gray-400">
              Press Enter or click Add to save the pattern
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
