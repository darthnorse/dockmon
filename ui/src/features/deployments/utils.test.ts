import { describe, it, expect } from 'vitest'
import { envFilesEqual, validateEnvFileName } from './utils'

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

describe('validateEnvFileName', () => {
  it('accepts bare env filenames', () => {
    expect(validateEnvFileName('.env')).toBeNull()
    expect(validateEnvFileName('.db.env')).toBeNull()
    expect(validateEnvFileName('prod.env')).toBeNull()
  })
  it('tolerates a leading ./ (compose same-dir form)', () => {
    expect(validateEnvFileName('./.env')).toBeNull()
    expect(validateEnvFileName('./db.env')).toBeNull()
  })
  it('rejects an empty name', () => {
    expect(validateEnvFileName('')).not.toBeNull()
  })
  it('rejects . and ..', () => {
    expect(validateEnvFileName('.')).not.toBeNull()
    expect(validateEnvFileName('..')).not.toBeNull()
    expect(validateEnvFileName('./..')).not.toBeNull()
  })
  it('rejects path separators and absolute paths', () => {
    expect(validateEnvFileName('sub/dir.env')).not.toBeNull()
    expect(validateEnvFileName('a\\b.env')).not.toBeNull()
    expect(validateEnvFileName('/abs.env')).not.toBeNull()
  })
  it('rejects leading/trailing whitespace', () => {
    expect(validateEnvFileName(' .env')).not.toBeNull()
    expect(validateEnvFileName('.env ')).not.toBeNull()
  })
})
