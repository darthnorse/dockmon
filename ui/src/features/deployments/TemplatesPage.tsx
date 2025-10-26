/**
 * Templates Management Page
 *
 * Browse, create, edit, and delete deployment templates
 * - List templates with category filtering
 * - Create custom templates
 * - Edit existing templates (user templates only)
 * - Delete templates (user templates only)
 * - Built-in templates are read-only
 */

import { useState } from 'react'
import { FileText, Plus, Edit, Trash2, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useTemplates, useDeleteTemplate } from './hooks/useTemplates'
import { TemplateForm } from './components/TemplateForm'
import type { DeploymentTemplate } from './types'

export function TemplatesPage() {
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const [showTemplateForm, setShowTemplateForm] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<DeploymentTemplate | null>(null)

  const { data: templates, isLoading, error } = useTemplates()
  const deleteTemplate = useDeleteTemplate()

  // Filter templates by category
  const filteredTemplates = templates?.filter(template => {
    if (!categoryFilter || categoryFilter === 'all') return true
    return template.category === categoryFilter
  }) || []

  // Get unique categories for filter
  const categories = Array.from(new Set(templates?.map(t => t.category).filter(Boolean) || []))

  const handleEdit = (template: DeploymentTemplate) => {
    if (template.is_builtin) {
      return // Built-in templates can't be edited
    }
    setEditingTemplate(template)
    setShowTemplateForm(true)
  }

  const handleDelete = (template: DeploymentTemplate) => {
    if (template.is_builtin) {
      return // Built-in templates can't be deleted
    }

    if (confirm(`Are you sure you want to delete template "${template.name}"?`)) {
      deleteTemplate.mutate(template.id)
    }
  }

  const handleCloseForm = () => {
    setShowTemplateForm(false)
    setEditingTemplate(null)
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <FileText className="h-8 w-8" />
            Deployment Templates
          </h1>
          <p className="text-muted-foreground mt-1">
            Reusable configurations for quick deployments
          </p>
        </div>

        <Button
          data-testid="new-template-button"
          onClick={() => setShowTemplateForm(true)}
          className="gap-2"
        >
          <Plus className="h-4 w-4" />
          New Template
        </Button>
      </div>

      {/* Filters */}
      <div className="flex gap-4">
        <Select
          value={categoryFilter || 'all'}
          onValueChange={(value) => setCategoryFilter(value === 'all' ? null : value)}
        >
          <SelectTrigger className="w-[200px]" data-testid="filter-category">
            <SelectValue placeholder="Filter by category" />
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

      {/* Loading State */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <p className="text-muted-foreground">Loading templates...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="flex items-center gap-2 p-4 bg-destructive/10 text-destructive rounded-lg">
          <AlertCircle className="h-5 w-5" />
          <p>Failed to load templates: {error.message}</p>
        </div>
      )}

      {/* Templates Table */}
      {!isLoading && !error && (
        <div className="rounded-lg border" data-testid="template-list">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredTemplates.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-12 text-muted-foreground">
                    No templates found. Create your first template to get started.
                  </TableCell>
                </TableRow>
              )}

              {filteredTemplates.map((template) => (
                <TableRow key={template.id} data-testid={`template-${template.name}`}>
                  {/* Name */}
                  <TableCell className="font-medium">{template.name}</TableCell>

                  {/* Category */}
                  <TableCell>
                    {template.category ? (
                      <Badge variant="outline">{template.category}</Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>

                  {/* Type */}
                  <TableCell className="capitalize">{template.deployment_type}</TableCell>

                  {/* Description */}
                  <TableCell className="max-w-xs truncate">
                    {template.description || '-'}
                  </TableCell>

                  {/* Source */}
                  <TableCell>
                    {template.is_builtin ? (
                      <Badge>Built-in</Badge>
                    ) : (
                      <Badge variant="secondary">Custom</Badge>
                    )}
                  </TableCell>

                  {/* Actions */}
                  <TableCell className="text-right space-x-2">
                    {!template.is_builtin && (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEdit(template)}
                          title="Edit"
                          data-testid={`edit-template-${template.name}`}
                        >
                          <Edit className="h-4 w-4" />
                        </Button>

                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(template)}
                          disabled={deleteTemplate.isPending}
                          title="Delete"
                          data-testid={`delete-template-${template.name}`}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </>
                    )}

                    {template.is_builtin && (
                      <span className="text-xs text-muted-foreground">Read-only</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Template Form Modal */}
      <TemplateForm
        isOpen={showTemplateForm}
        onClose={handleCloseForm}
        template={editingTemplate}
      />
    </div>
  )
}
