import { describe, it, expect } from 'vitest'
import { envFilesEqual } from './utils'

describe('envFilesEqual', () => {
  it('equal for same keys and values', () => {
    expect(envFilesEqual({ '.env': 'A=1' }, { '.env': 'A=1' })).toBe(true)
  })
  it('differs when a value changes', () => {
    expect(envFilesEqual({ '.env': 'A=1' }, { '.env': 'A=2' })).toBe(false)
  })
  it('differs when a key is added or removed', () => {
    expect(envFilesEqual({ '.env': 'A=1' }, { '.env': 'A=1', '.db.env': 'B=2' })).toBe(false)
  })
  it('order-independent', () => {
    expect(envFilesEqual({ a: '1', b: '2' }, { b: '2', a: '1' })).toBe(true)
  })
  it('two empty maps are equal', () => {
    expect(envFilesEqual({}, {})).toBe(true)
  })
})
