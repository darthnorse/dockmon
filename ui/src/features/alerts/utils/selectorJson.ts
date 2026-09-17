import type { SelectorJson } from '@/types/alerts'

/** Parse a stored host/container selector; missing or malformed JSON reads as an empty selector. */
export function parseSelectorJson(json: string | null | undefined): SelectorJson {
  if (!json) return {}
  try {
    const parsed: unknown = JSON.parse(json)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return {}
    return parsed as SelectorJson
  } catch {
    return {}
  }
}
