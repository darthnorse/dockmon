/**
 * Add Custom Column Dialog (Issue #207).
 *
 * Lets the user add an env-var or label as a column in the containers table.
 * Form: kind (env/label) + name (free text). Validates non-empty and
 * deduplicates against existing column IDs.
 */
import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface AddCustomColumnDialogProps {
  open: boolean
  existingColumnIds: string[]
  onOpenChange: (open: boolean) => void
  onAdd: (columnId: string) => void
}

export function AddCustomColumnDialog({
  open,
  existingColumnIds,
  onOpenChange,
  onAdd,
}: AddCustomColumnDialogProps) {
  const [kind, setKind] = useState<'env' | 'label'>('env')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Name is required')
      return
    }
    const id = `${kind}:${trimmed}`
    if (existingColumnIds.includes(id)) {
      setError('This column already exists')
      return
    }
    onAdd(id)
    setName('')
    setError(null)
    onOpenChange(false)
  }

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setName('')
      setError(null)
    }
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Custom Column</DialogTitle>
          <DialogDescription>
            Show a Docker environment variable or label as a column in the table.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div>
            <label className="block text-sm font-medium mb-2">Source</label>
            <div className="flex gap-2">
              <Button
                type="button"
                variant={kind === 'env' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setKind('env')}
              >
                Environment variable
              </Button>
              <Button
                type="button"
                variant={kind === 'label' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setKind('label')}
              >
                Docker label
              </Button>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              {kind === 'env' ? 'Variable name' : 'Label name'}
            </label>
            <Input
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                setError(null)
              }}
              placeholder={kind === 'env' ? 'VIRTUAL_HOST' : 'com.acme.url'}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              autoFocus
            />
            {error && <p className="text-sm text-destructive mt-1">{error}</p>}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit}>Add column</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
