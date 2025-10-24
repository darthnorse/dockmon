/**
 * Containers Page - Phase 3b
 *
 * FEATURES:
 * - Real-time container list with TanStack Table
 * - Container actions (start/stop/restart)
 * - Search and filter
 * - Auto-refresh every 5s
 */

import { ContainerTable } from './ContainerTable'

export function ContainersPage() {
  return (
    <div className="p-6">
      {/* Page Header */}
      <div className="mb-6">
        <div>
          <h1 className="text-2xl font-bold">Containers</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage and monitor Docker containers
          </p>
        </div>
      </div>

      {/* Container Table */}
      <ContainerTable />
    </div>
  )
}
