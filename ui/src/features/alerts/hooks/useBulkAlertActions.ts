import { toast } from 'sonner'
import { useBatchResolveAlerts, useBatchSnoozeAlerts } from './useAlerts'
import { describeBatchOutcome } from '../utils/batchOutcome'

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown error'
}

/** Bulk resolve/snooze in one request each; resolves to true when the selection can be cleared. */
export function useBulkAlertActions() {
  const batchResolve = useBatchResolveAlerts()
  const batchSnooze = useBatchSnoozeAlerts()

  const resolve = async (alertIds: string[], reason?: string): Promise<boolean> => {
    try {
      const result = await batchResolve.mutateAsync({ alertIds, ...(reason ? { reason } : {}) })
      const outcome = describeBatchOutcome(result)
      if (outcome) toast.info(outcome)
      return true
    } catch (error) {
      toast.error(`Failed to resolve alerts: ${errorMessage(error)}`)
      return false
    }
  }

  const snooze = async (alertIds: string[], durationMinutes: number): Promise<boolean> => {
    try {
      const result = await batchSnooze.mutateAsync({ alertIds, durationMinutes })
      const outcome = describeBatchOutcome(result)
      if (outcome) toast.info(outcome)
      return true
    } catch (error) {
      toast.error(`Failed to snooze alerts: ${errorMessage(error)}`)
      return false
    }
  }

  return {
    resolve,
    snooze,
    isResolving: batchResolve.isPending,
    isSnoozing: batchSnooze.isPending,
  }
}
