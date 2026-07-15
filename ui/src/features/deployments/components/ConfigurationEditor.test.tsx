/**
 * Regression: a TAB in a compose file slipped past the editor (js-yaml is
 * lenient) and only surfaced as a confusing deploy-time error. The editor now
 * flags tabs used in indentation up front, with a clear line number.
 */
import { describe, it, expect } from 'vitest'

import { findIndentationTab } from './ConfigurationEditor'

describe('findIndentationTab', () => {
  it('returns null for space-indented YAML', () => {
    expect(findIndentationTab('services:\n  app:\n    image: nginx\n')).toBeNull()
  })

  it('flags a leading indentation tab with its 1-based line number', () => {
    expect(findIndentationTab('services:\n\tapp:\n\t\timage: nginx\n')).toBe(2)
  })

  it('flags a tab mixed after leading spaces', () => {
    expect(findIndentationTab('services:\n  app:\n    image: nginx\n  \tweb:\n')).toBe(4)
  })

  it('does not flag a tab that is not in the indentation', () => {
    // Non-leading structural tabs are the backend PyYAML gate's job.
    expect(findIndentationTab('services:\n  app:\n    image:\tnginx\n')).toBeNull()
  })

  it('does not flag a tab inside a value', () => {
    expect(findIndentationTab('services:\n  app:\n    command: echo\thi\n')).toBeNull()
  })

  it('returns the first offending line when several have tabs', () => {
    expect(findIndentationTab('a:\n  b: 1\n\tc: 2\n\td: 3\n')).toBe(3)
  })

  // Block scalars: a leading tab in `| / >` content is literal, valid YAML
  // (PyYAML accepts it), so it must NOT be flagged.
  it('does not flag a tab starting block-scalar content (literal |)', () => {
    expect(findIndentationTab('services:\n  app:\n    command: |\n      \techo hi\n')).toBeNull()
  })

  it('does not flag tabs across multiple block-scalar content lines', () => {
    expect(
      findIndentationTab('services:\n  app:\n    command: |\n      \tline1\n      \tline2\n'),
    ).toBeNull()
  })

  it('handles folded and chomped introducers (> and |-)', () => {
    expect(findIndentationTab('a:\n  x: >\n    \tfolded\n')).toBeNull()
    expect(findIndentationTab('a:\n  x: |-\n    \tkept\n')).toBeNull()
  })

  it('still flags a structural tab AFTER a block scalar ends', () => {
    // Block content is skipped, but the dedented `\tweb:` is real indentation.
    expect(
      findIndentationTab('services:\n  app:\n    command: |\n      echo hi\n\tweb:\n'),
    ).toBe(5)
  })

  it('does not treat a piped value as a block scalar', () => {
    // `foo | bar` is a plain scalar, not a block introducer; a later tab still flags.
    expect(findIndentationTab('a:\n  x: foo | bar\n\ty: 1\n')).toBe(3)
  })
})
