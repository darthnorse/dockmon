/**
 * CollapsibleSection Component
 * Reusable collapsible section with icon and title
 */

import { useState, ReactNode } from 'react'
import { ChevronDown, ChevronRight, LucideIcon } from 'lucide-react'

interface Props {
  title: string
  icon: LucideIcon
  children: ReactNode
  defaultOpen?: boolean
}

export function CollapsibleSection({ title, icon: Icon, children, defaultOpen = true }: Props) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-3 p-4 hover:bg-gray-800/30 transition-colors"
      >
        <Icon className="h-5 w-5 text-gray-400 flex-shrink-0" />
        <h2 className="text-lg font-semibold text-white flex-1 text-left">{title}</h2>
        {isOpen ? (
          <ChevronDown className="h-5 w-5 text-gray-400" />
        ) : (
          <ChevronRight className="h-5 w-5 text-gray-400" />
        )}
      </button>

      {isOpen && (
        <div className="p-6 pt-0 border-t border-border">
          {children}
        </div>
      )}
    </div>
  )
}
