import { describe, it, expect } from 'vitest'
import { ensureValidNavigatorLocale, toValidLocale } from './ensureValidLocale'

function fakeNavigator(language: string, languages: string[] = [language]) {
  const nav = Object.create({ language, languages }) as Navigator
  return nav
}

describe('toValidLocale', () => {
  it('keeps a valid tag', () => {
    expect(toValidLocale('de-DE')).toBe('de-DE')
  })

  it('strips a POSIX modifier', () => {
    expect(toValidLocale('en-US@posix')).toBe('en-US')
  })

  it('converts a glibc-style locale', () => {
    expect(toValidLocale('en_US.UTF-8')).toBe('en-US')
  })

  it('rejects what cannot be repaired', () => {
    expect(toValidLocale('C')).toBeNull()
    expect(toValidLocale('')).toBeNull()
  })
})

describe('ensureValidNavigatorLocale', () => {
  it('leaves a valid browser locale alone', () => {
    const nav = fakeNavigator('fr-FR')

    ensureValidNavigatorLocale(nav)

    expect(Object.getOwnPropertyDescriptor(nav, 'language')).toBeUndefined()
    expect(nav.language).toBe('fr-FR')
  })

  it('repairs an invalid locale so Intl accepts it', () => {
    const nav = fakeNavigator('en-US@posix')

    ensureValidNavigatorLocale(nav)

    expect(nav.language).toBe('en-US')
    expect(() => new Intl.NumberFormat(nav.language)).not.toThrow()
  })

  it('falls back to the next usable preferred language', () => {
    const nav = fakeNavigator('C', ['C', 'sv_SE.UTF-8'])

    ensureValidNavigatorLocale(nav)

    expect(nav.language).toBe('sv-SE')
  })

  it('falls back to en-US when nothing is usable', () => {
    const nav = fakeNavigator('C', ['C'])

    ensureValidNavigatorLocale(nav)

    expect(nav.language).toBe('en-US')
  })
})
