import { describe, it, expect } from 'vitest'
import { parseSelectorJson } from './selectorJson'

describe('parseSelectorJson', () => {
  it('returns the parsed selector', () => {
    expect(parseSelectorJson('{"include":["h1"],"should_run":true}')).toEqual({ include: ['h1'], should_run: true })
  })

  it('reads null, empty and malformed input as an empty selector', () => {
    expect(parseSelectorJson(null)).toEqual({})
    expect(parseSelectorJson('')).toEqual({})
    expect(parseSelectorJson('{not json')).toEqual({})
  })

  it('reads valid JSON that is not an object as an empty selector', () => {
    expect(parseSelectorJson('null')).toEqual({})
    expect(parseSelectorJson('["h1"]')).toEqual({})
    expect(parseSelectorJson('"include_all"')).toEqual({})
  })
})
