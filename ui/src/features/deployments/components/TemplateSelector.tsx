/**
 * Template Selector Component
 *
 * Modal for selecting a deployment template
 * - Lists available templates
 * - Category filtering
 * - Search functionality
 */

import { useState } from 'react'
import { Search, Layers } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { useTemplates } from '../hooks/useTemplates'
import type { DeploymentTemplate } from '../types'

interface TemplateSelectorProps {
  isOpen: boolean
  onClose: () => void
  onSelect: (template: DeploymentTemplate) => void
}

export function TemplateSelector({ isOpen, onClose, onSelect }: TemplateSelectorProps) {
  const { data: templates, isLoading } = useTemplates()
  const [searchQuery, setSearchQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)

  // Get unique categories
  const categories = Array.from(new Set(templates?.map(t => t.category).filter(Boolean) || []))

  // Filter templates
  const filteredTemplates = templates?.filter(template => {
    // Category filter
    if (categoryFilter && categoryFilter !== 'all' && template.category !== categoryFilter) {
      return false
    }

    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        template.name.toLowerCase().includes(query) ||
        template.description?.toLowerCase().includes(query) ||
        template.category?.toLowerCase().includes(query)
      )
    }

    return true
  }) || []

  const handleSelect = (template: DeploymentTemplate) => {
    onSelect(template)
    onClose()
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[80vh]" data-testid="template-selector">
        <DialogHeader>
          <DialogTitle>Select a Template</DialogTitle>
          <DialogDescription>
            Choose a template to prefill your deployment configuration
          </DialogDescription>
        </DialogHeader>

        {/* Search and Filter */}
        <div className="space-y-4">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search templates..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>

            <Select
              value={categoryFilter || 'all'}
              onValueChange={(value) => setCategoryFilter(value === 'all' ? null : value)}
            >
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="All categories" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Categories</SelectItem>
                {categories.map(category => (
                  <SelectItem key={category} value={category || ''}>
                    {category}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Template List */}
        <div className="space-y-2 max-h-[400px] overflow-y-auto">
          {isLoading && (
            <div className="text-center py-8 text-muted-foreground">
              Loading templates...
            </div>
          )}

          {!isLoading && filteredTemplates.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              No templates found
            </div>
          )}

          {!isLoading && filteredTemplates.map((template) => (
            <button
              key={template.id}
              data-testid={`template-${template.name}`}
              onClick={() => handleSelect(template)}
              className="w-full text-left p-4 rounded-lg border border-border hover:border-primary hover:bg-surface-2 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <Layers className="h-4 w-4 text-muted-foreground" />
                    <h4 className="font-semibold">{template.name}</h4>
                    {template.is_builtin && (
                      <Badge variant="outline" className="text-xs">Built-in</Badge>
                    )}
                    {template.category && (
                      <Badge variant="secondary" className="text-xs">{template.category}</Badge>
                    )}
                  </div>

                  {template.description && (
                    <p className="text-sm text-muted-foreground line-clamp-2">
                      {template.description}
                    </p>
                  )}

                  <p className="text-xs text-muted-foreground capitalize">
                    Type: {template.deployment_type}
                  </p>
                </div>

                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="flex-shrink-0"
                >
                  Select
                </Button>
              </div>
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
