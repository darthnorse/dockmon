import { toast } from 'sonner'
import type { BatchResolveResult, BatchSnoozeResult } from '@/types/alerts'
import { getErrorMessage } from '@/lib/utils/errors'
import { useBatchResolveAlerts, useBatchSnoozeAlerts } from './useAlerts'
import { describeBatchOutcome } from '../utils/batchOutcome'

/** Bulk resolve/snooze in one request each; resolves to true when the selection can be cleared. */
export function useBulkAlertActions() {
  const batchResolve = useBatchResolveAlerts()
  const batchSnooze = useBatchSnoozeAlerts()

  const run = async (
    action: string,
    call: () => Promise<BatchResolveResult | BatchSnoozeResult>,
  ): Promise<boolean> => {
    try {
      const outcome = describeBatchOutcome(await call())
      if (outcome) toast.info(outcome)
      return true
    } catch (error) {
      toast.error(`Failed to ${action} alerts: ${getErrorMessage(error, 'Unknown error')}`)
      return false
    }
  }

  return {
    resolve: (alertIds: string[], reason?: string) =>
      run('resolve', () => batchResolve.mutateAsync({ alertIds, ...(reason ? { reason } : {}) })),
    snooze: (alertIds: string[], durationMinutes: number) =>
      run('snooze', () => batchSnooze.mutateAsync({ alertIds, durationMinutes })),
    isResolving: batchResolve.isPending,
    isSnoozing: batchSnooze.isPending,
  }
}
