import { describe, it, expect } from 'vitest'
import {
  parseColumnId,
  getColumnLabel,
  extractColumnValue,
  isCustomColumnId,
} from './customColumns'

describe('parseColumnId', () => {
  it('parses env: prefix', () => {
    expect(parseColumnId('env:VIRTUAL_HOST')).toEqual({
      kind: 'env',
      name: 'VIRTUAL_HOST',
    })
  })

  it('parses label: prefix', () => {
    expect(parseColumnId('label:com.acme.url')).toEqual({
      kind: 'label',
      name: 'com.acme.url',
    })
  })

  it('treats unknown prefix as builtin', () => {
    expect(parseColumnId('name')).toEqual({ kind: 'builtin', name: 'name' })
  })

  it('preserves names containing colons (label only takes one split)', () => {
    expect(parseColumnId('label:io.acme.tag:v1')).toEqual({
      kind: 'label',
      name: 'io.acme.tag:v1',
    })
  })

  it('treats prefix-only id as builtin (defensive against malformed input)', () => {
    expect(parseColumnId('env:')).toEqual({ kind: 'builtin', name: 'env:' })
    expect(parseColumnId('label:')).toEqual({ kind: 'builtin', name: 'label:' })
  })
})

describe('isCustomColumnId', () => {
  it('returns true for env:', () => {
    expect(isCustomColumnId('env:X')).toBe(true)
  })
  it('returns true for label:', () => {
    expect(isCustomColumnId('label:X')).toBe(true)
  })
  it('returns false for builtins', () => {
    expect(isCustomColumnId('name')).toBe(false)
  })
})

describe('getColumnLabel', () => {
  it('formats env column label as "ENV: VARNAME"', () => {
    expect(getColumnLabel('env:VIRTUAL_HOST')).toBe('ENV: VIRTUAL_HOST')
  })
  it('formats label column label as "LABEL: name"', () => {
    expect(getColumnLabel('label:com.acme.url')).toBe('LABEL: com.acme.url')
  })
  it('passes through builtin IDs (caller should map separately)', () => {
    expect(getColumnLabel('name')).toBe('name')
  })
})

describe('extractColumnValue', () => {
  const container = {
    env: { VIRTUAL_HOST: 'app.example.com', EMPTY: '' },
    labels: { 'com.acme.url': 'https://x' },
  }

  it('returns env value when present', () => {
    expect(extractColumnValue(container, 'env:VIRTUAL_HOST')).toBe('app.example.com')
  })
  it('returns label value when present', () => {
    expect(extractColumnValue(container, 'label:com.acme.url')).toBe('https://x')
  })
  it('returns empty string for missing env', () => {
    expect(extractColumnValue(container, 'env:MISSING')).toBe('')
  })
  it('returns empty string for missing label', () => {
    expect(extractColumnValue(container, 'label:missing')).toBe('')
  })
  it('returns empty string when env is undefined on container', () => {
    expect(extractColumnValue({}, 'env:X')).toBe('')
  })
  it('returns null for builtin IDs (caller resolves builtin columns)', () => {
    expect(extractColumnValue(container, 'name')).toBeNull()
  })
})
