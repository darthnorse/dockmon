/**
 * Agents Management Page for DockMon v2.2.0
 *
 * Main page for registering and managing remote Docker agents
 */

import { AgentRegistration } from './components/AgentRegistration'
import { AgentList } from './components/AgentList'

export function AgentsPage() {
  return (
    <div className="container mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Agents</h1>
        <p className="text-muted-foreground mt-2">
          Manage DockMon agents installed on remote Docker hosts
        </p>
      </div>

      <AgentRegistration />

      <AgentList />
    </div>
  )
}
