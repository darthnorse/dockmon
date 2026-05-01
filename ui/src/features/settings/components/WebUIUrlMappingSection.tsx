/**
 * WebUI URL Mapping Section (Issue #207).
 *
 * Admin-only editor for the global webui_url_mapping_chain. Users can add,
 * remove, and reorder template strings. The first template that resolves to
 * a non-empty value (when evaluated against a container's env and labels)
 * wins. Templates support ${env:NAME} and ${label:NAME} placeholders.
 *
 * The parent SystemSettings component wraps everything in a fieldset that
 * disables the form for users without the settings.manage capability, so
 * we don't need to handle disabled state here.
 */
import { useEffect, useState } from 'react'
import { Plus, Trash2, ArrowUp, ArrowDown } from 'lucide-react'
import { toast } from 'sonner'
import { useGlobalSettings, useUpdateGlobalSettings } from '@/hooks/useSettings'

export function WebUIUrlMappingSection() {
  const { data: settings } = useGlobalSettings()
  const updateSettings = useUpdateGlobalSettings()

  const [chain, setChain] = useState<string[]>(settings?.webui_url_mapping_chain ?? [])

  useEffect(() => {
    if (settings) {
      setChain(settings.webui_url_mapping_chain ?? [])
    }
  }, [settings])

  const persist = async (next: string[]) => {
    setChain(next)
    try {
      await updateSettings.mutateAsync({ webui_url_mapping_chain: next })
    } catch {
      toast.error('Failed to update WebUI URL mapping')
    }
  }

  const handleAdd = () => persist([...chain, ''])
  const handleUpdate = (i: number, value: string) => {
    const next = [...chain]
    next[i] = value
    setChain(next) // local-only on keystroke
  }
  const handleBlur = (i: number) => {
    // commit on blur, but only if the value changed from server state
    const original = settings?.webui_url_mapping_chain ?? []
    if (chain[i] !== original[i]) {
      void persist([...chain])
    }
  }
  const handleRemove = (i: number) => persist(chain.filter((_, idx) => idx !== i))
  const handleMove = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= chain.length) return
    const next = [...chain]
    const a = next[i] ?? ''
    const b = next[j] ?? ''
    next[i] = b
    next[j] = a
    void persist(next)
  }

  return (
    <div>
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-white">WebUI URL auto-mapping</h3>
        <p className="text-xs text-gray-400 mt-1">
          When a container has no manually-set WebUI URL, DockMon evaluates these
          templates in order against its environment variables and Docker labels.
          The first template that resolves to a non-empty URL is used. Manually-set
          URLs always take precedence.
        </p>
        <p className="text-xs text-gray-500 mt-2">
          Placeholders: <code className="text-gray-300">{'${env:NAME}'}</code> for env vars,{' '}
          <code className="text-gray-300">{'${label:NAME}'}</code> for Docker labels. Example:{' '}
          <code className="text-gray-300">{'https://${env:VIRTUAL_HOST}'}</code>
        </p>
      </div>

      <div className="space-y-2">
        {chain.length === 0 && (
          <p className="text-sm text-gray-500 italic">
            No templates configured. Auto-mapping is disabled.
          </p>
        )}
        {chain.map((template, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="text-xs text-gray-500 w-6 text-right">{i + 1}.</span>
            <input
              type="text"
              value={template}
              onChange={(e) => handleUpdate(i, e.target.value)}
              onBlur={() => handleBlur(i)}
              placeholder="https://${env:VIRTUAL_HOST}"
              className="flex-1 rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <button
              type="button"
              onClick={() => handleMove(i, -1)}
              disabled={i === 0}
              title="Move up"
              className="p-2 text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => handleMove(i, 1)}
              disabled={i === chain.length - 1}
              title="Move down"
              className="p-2 text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ArrowDown className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => handleRemove(i)}
              title="Remove"
              className="p-2 text-gray-400 hover:text-red-400"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={handleAdd}
        className="mt-3 inline-flex items-center gap-2 rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700"
      >
        <Plus className="h-3.5 w-3.5" />
        Add template
      </button>
    </div>
  )
}
