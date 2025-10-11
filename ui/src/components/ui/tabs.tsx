/**
 * Tabs Component
 *
 * Simple tab navigation component
 * - Clean, minimal design
 * - Active state styling
 * - Keyboard navigation support
 */

import { cn } from '@/lib/utils'
import { ReactNode } from 'react'

export interface TabsProps {
  /**
   * Array of tab items
   */
  tabs: Array<{
    id: string
    label: string
    content: ReactNode
  }>

  /**
   * Currently active tab ID
   */
  activeTab: string

  /**
   * Callback when tab is changed
   */
  onTabChange: (tabId: string) => void

  /**
   * Optional className for the tabs container
   */
  className?: string
}

export function Tabs({ tabs, activeTab, onTabChange, className }: TabsProps) {
  return (
    <div className={cn('w-full flex flex-col', className)}>
      {/* Tab Navigation */}
      <div className="border-b border-border shrink-0">
        <nav className="flex gap-6 px-6 pt-4" aria-label="Tabs">
          {tabs.map((tab) => {
            const isActive = tab.id === activeTab

            return (
              <button
                key={tab.id}
                onClick={() => onTabChange(tab.id)}
                className={cn(
                  'relative pb-3 text-sm font-medium transition-colors',
                  'hover:text-foreground focus:outline-none',
                  isActive
                    ? 'text-foreground'
                    : 'text-muted-foreground'
                )}
                aria-current={isActive ? 'page' : undefined}
              >
                {tab.label}

                {/* Active indicator */}
                {isActive && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-accent" />
                )}
              </button>
            )
          })}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-y-auto">
        {tabs.find((tab) => tab.id === activeTab)?.content}
      </div>
    </div>
  )
}
