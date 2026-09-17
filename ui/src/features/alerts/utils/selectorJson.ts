import type { SelectorJson } from '@/types/alerts'

/** Parse a stored host/container selector; missing or malformed JSON reads as an empty selector. */
export function parseSelectorJson(json: string | null | undefined): SelectorJson {
  if (!json) return {}
  try {
    return JSON.parse(json) as SelectorJson
  } catch {
    return {}
  }
}
