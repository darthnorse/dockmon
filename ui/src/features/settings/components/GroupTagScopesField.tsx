/**
 * Host-visibility picker for the group editor.
 *
 * Selection is by tag id (names can collide across renames). An empty selection
 * means the group is unrestricted and its members see every host.
 */

import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import type { HostTagWithMeta } from '@/types/groups'

interface GroupTagScopesFieldProps {
  tags: HostTagWithMeta[]
  selectedIds: string[]
  onChange: (ids: string[]) => void
  isLoading?: boolean
}

export function GroupTagScopesField({ tags, selectedIds, onChange, isLoading = false }: GroupTagScopesFieldProps) {
  const toggle = (id: string, checked: boolean) => {
    onChange(checked ? [...selectedIds, id] : selectedIds.filter((s) => s !== id))
  }

  return (
    <div className="grid gap-2">
      <Label>Host visibility</Label>
      <p className="text-xs text-muted-foreground">
        Members see only hosts carrying a selected tag. Empty = unrestricted (members see all hosts).
      </p>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading host tags…</p>
      ) : tags.length === 0 ? (
        <p className="text-sm text-muted-foreground">No host tags yet. Tag a host first to scope a group.</p>
      ) : (
        <ul className="max-h-48 overflow-y-auto rounded-md border p-2" role="group" aria-label="Host visibility tags">
          {tags.map((tag) => {
            const inputId = `tag-scope-${tag.id}`
            return (
              <li key={tag.id} className="flex items-center gap-2 py-1">
                <Checkbox
                  id={inputId}
                  checked={selectedIds.includes(tag.id)}
                  onCheckedChange={(checked) => toggle(tag.id, checked === true)}
                />
                <Label htmlFor={inputId} className="flex cursor-pointer items-center gap-2 font-normal">
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-full border"
                    style={{ backgroundColor: tag.color ?? undefined }}
                    aria-hidden="true"
                  />
                  {tag.name}
                </Label>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
