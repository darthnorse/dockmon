import { useEffect, useRef, useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { toast } from 'sonner'

interface EnvVarListProps {
  entries: [string, string][]
}

const COPIED_FEEDBACK_MS = 2000

export function EnvVarList({ entries }: EnvVarListProps) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => () => clearTimeout(timerRef.current), [])

  const copyValue = async (index: number, value: string) => {
    try {
      // navigator.clipboard is undefined on insecure (plain HTTP) origins.
      if (!navigator.clipboard) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(value)
      setCopiedIndex(index)
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => setCopiedIndex(null), COPIED_FEEDBACK_MS)
    } catch {
      toast.error('Could not copy to clipboard')
    }
  }

  return (
    <div className="space-y-1.5 max-h-64 overflow-y-auto">
      {entries.map(([key, value], index) => (
        <div key={`${index}:${key}`} className="flex items-start gap-3 text-sm">
          <span className="text-muted-foreground font-mono shrink-0 max-w-[45%] break-all">{key}</span>
          <span className="font-mono min-w-0 flex-1 break-all whitespace-pre-wrap text-right">{value}</span>
          <button
            type="button"
            onClick={() => void copyValue(index, value)}
            className="shrink-0 p-0.5 text-muted-foreground hover:text-foreground transition-colors"
            aria-label={`Copy value of ${key}`}
            title="Copy value"
          >
            {copiedIndex === index ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
        </div>
      ))}
    </div>
  )
}
