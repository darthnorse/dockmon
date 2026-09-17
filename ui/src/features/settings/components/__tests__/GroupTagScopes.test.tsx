/**
 * GroupTagScopesField - id-based host-visibility picker for the group editor.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GroupTagScopesField } from '../GroupTagScopesField'

const TAGS = [
  { id: 'tag-dev', name: 'dev', color: '#3b82f6' },
  { id: 'tag-prod', name: 'prod', color: null },
]

describe('GroupTagScopesField', () => {
  it('explains that an empty selection is unrestricted', () => {
    render(<GroupTagScopesField tags={TAGS} selectedIds={[]} onChange={vi.fn()} />)
    expect(screen.getByText(/Empty = unrestricted/)).toBeInTheDocument()
  })

  it('renders every tag with its selection state', () => {
    render(<GroupTagScopesField tags={TAGS} selectedIds={['tag-prod']} onChange={vi.fn()} />)
    expect(screen.getByLabelText('dev')).not.toBeChecked()
    expect(screen.getByLabelText('prod')).toBeChecked()
  })

  it('reports selection changes by tag id', async () => {
    const onChange = vi.fn()
    render(<GroupTagScopesField tags={TAGS} selectedIds={['tag-prod']} onChange={onChange} />)
    await userEvent.click(screen.getByLabelText('dev'))
    expect(onChange).toHaveBeenLastCalledWith(['tag-prod', 'tag-dev'])
    await userEvent.click(screen.getByLabelText('prod'))
    expect(onChange).toHaveBeenLastCalledWith([])
  })

  it('tells the admin when no host tag exists yet', () => {
    render(<GroupTagScopesField tags={[]} selectedIds={[]} onChange={vi.fn()} />)
    expect(screen.getByText(/Tag a host first/)).toBeInTheDocument()
  })
})
