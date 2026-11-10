import type { BatchResolveResult, BatchSnoozeResult } from '@/types/alerts'

export function describeBatchOutcome(result: BatchResolveResult | BatchSnoozeResult): string | null {
  const changed = 'resolved' in result ? result.resolved.length : result.snoozed.length
  const verb = 'resolved' in result ? 'resolved' : 'snoozed'
  const parts: string[] = []
  const alreadyResolved = result.skipped.length
  if (alreadyResolved > 0) parts.push(`${alreadyResolved} already resolved`)
  if (result.not_found.length > 0) parts.push(`${result.not_found.length} no longer available`)
  if (parts.length === 0) return null
  return `${changed} alert${changed === 1 ? '' : 's'} ${verb}; ${parts.join(', ')}`
}
