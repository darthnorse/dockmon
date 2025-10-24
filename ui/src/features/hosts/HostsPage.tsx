/**
 * Hosts Page - Phase 3d Sub-Phase 6
 *
 * FEATURES:
 * - Complete hosts management page
 * - Search bar for filtering
 * - "+ Add Host" button
 * - HostTable with all 10 columns
 * - HostModal for add/edit operations
 * - Empty state when no hosts
 *
 * LAYOUT:
 * - Page header with title
 * - Search and action buttons
 * - HostTable component
 * - Loading skeleton
 */

import { useState } from 'react'
import { Plus, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { HostTable } from './components/HostTable'
import { HostModal } from './components/HostModal'
import type { Host } from '@/types/api'

export function HostsPage() {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [selectedHost, setSelectedHost] = useState<Host | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const handleAddHost = () => {
    setSelectedHost(null)
    setIsModalOpen(true)
  }

  const handleEditHost = (host: Host) => {
    setSelectedHost(host)
    setIsModalOpen(true)
  }

  const handleCloseModal = () => {
    setIsModalOpen(false)
    setSelectedHost(null)
  }

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Hosts</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage your Docker hosts and connections
          </p>
        </div>
        <Button onClick={handleAddHost} className="flex items-center gap-2" data-testid="add-host-button">
          <Plus className="h-4 w-4" />
          Add Host
        </Button>
      </div>

      {/* Search and Filters */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            type="text"
            placeholder="Search hosts by name, URL, or tags..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
            data-testid="hosts-search-input"
          />
        </div>
        {/* TODO: Add filter dropdowns (status, tags, group) */}
      </div>

      {/* Host Table */}
      <HostTable onEditHost={handleEditHost} />

      {/* Host Modal */}
      <HostModal
        isOpen={isModalOpen}
        onClose={handleCloseModal}
        host={selectedHost}
      />
    </div>
  )
}
