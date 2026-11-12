const FALLBACK_LOCALE = 'en-US'

function isValidLocale(tag: string): boolean {
  try {
    new Intl.NumberFormat(tag)
    return true
  } catch {
    return false
  }
}

/** Repair POSIX/glibc locale names ("en-US@posix", "en_US.UTF-8") into a BCP 47 tag, or null. */
export function toValidLocale(tag: string): string | null {
  if (!tag) return null
  if (isValidLocale(tag)) return tag
  const repaired = tag.split(/[@.]/)[0]?.replace(/_/g, '-') ?? ''
  return repaired && isValidLocale(repaired) ? repaired : null
}

/**
 * Some browsers (e.g. Chromium under LANG=C) report a navigator.language that
 * Intl rejects. uPlot builds `new Intl.NumberFormat(navigator.language)` at
 * import time, so that RangeError aborts the whole bundle and the page stays
 * blank. Shadow the property with a usable locale before any library loads.
 */
export function ensureValidNavigatorLocale(nav: Navigator = navigator): void {
  if (isValidLocale(nav.language)) return
  const preferred = [nav.language, ...(nav.languages ?? [])]
  const locale = preferred.map(toValidLocale).find((l): l is string => l !== null) ?? FALLBACK_LOCALE
  Object.defineProperty(nav, 'language', { value: locale, configurable: true })
  Object.defineProperty(nav, 'languages', { value: Object.freeze([locale]), configurable: true })
}

if (typeof navigator !== 'undefined') ensureValidNavigatorLocale()
