/**
 * Containers Page - Phase 3b
 *
 * FEATURES:
 * - Real-time container list with TanStack Table
 * - Container actions (start/stop/restart)
 * - Search and filter
 * - Auto-refresh every 5s
 */

import { Container } from 'lucide-react'
import { ContainerTable } from './ContainerTable'

export function ContainersPage() {
  return (
    <div className="p-6">
      {/* Page Header */}
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
          <Container className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold">Containers</h1>
          <p className="text-sm text-muted-foreground">
            Manage and monitor Docker containers
          </p>
        </div>
      </div>

      {/* Container Table */}
      <ContainerTable />
    </div>
  )
}
