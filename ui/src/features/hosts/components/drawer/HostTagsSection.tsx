/**
 * Host Tags Section for HostDrawer
 * Displays and allows editing of host tags (prod, dev, regions, etc.)
 */

import { Tag, Plus } from 'lucide-react'
import { TagInput } from '@/components/TagInput'
import { TagChip } from '@/components/TagChip'
import { Button } from '@/components/ui/button'
import { Host } from '@/types/api'
import { useHostTagEditor } from '@/hooks/useHostTagEditor'

interface HostTagsSectionProps {
  host: Host
}

export function HostTagsSection({ host }: HostTagsSectionProps) {
  const currentTags = host.tags || []

  const {
    isEditing,
    editedTags,
    tagSuggestions,
    isLoading,
    setEditedTags,
    handleStartEdit,
    handleCancelEdit,
    handleSaveTags,
  } = useHostTagEditor({ hostId: host.id, currentTags })

  return (
    <div className="border-b border-border">
      <div className="px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Tag className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-medium">Host Tags</h3>
          </div>
          {!isEditing && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleStartEdit}
              className="h-7 px-2"
            >
              <Plus className="h-3 w-3 mr-1" />
              Edit
            </Button>
          )}
        </div>

        {isEditing ? (
          <div className="space-y-3">
            <TagInput
              value={editedTags}
              onChange={setEditedTags}
              suggestions={tagSuggestions}
              placeholder="Add host tags (prod, dev, us-west-1...)"
              maxTags={20}
            />
            <div className="flex gap-2">
              <Button
                variant="default"
                size="sm"
                onClick={handleSaveTags}
                disabled={isLoading}
                className="flex-1"
              >
                Save Tags
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCancelEdit}
                disabled={isLoading}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {currentTags.length === 0 ? (
              <p className="text-sm text-muted-foreground">No tags</p>
            ) : (
              currentTags.map((tag) => (
                <TagChip
                  key={tag}
                  tag={tag}
                />
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}
