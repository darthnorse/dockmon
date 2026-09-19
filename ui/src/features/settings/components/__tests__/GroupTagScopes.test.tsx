/**
 * GroupTagScopesField - id-based host-visibility picker for the group editor.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
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

// ---------------------------------------------------------------------------
// EditGroupModal: the picker must reflect THIS group's stored scopes before it
// can be edited, or a save could replace them from the wrong baseline.
// ---------------------------------------------------------------------------

vi.mock('@/hooks/useGroups', () => ({
  useGroups: vi.fn(),
  useGroup: vi.fn(),
  useCreateGroup: vi.fn(),
  useUpdateGroup: vi.fn(),
  useDeleteGroup: vi.fn(),
  useAddGroupMember: vi.fn(),
  useRemoveGroupMember: vi.fn(),
  useGroupTagScopes: vi.fn(),
  useUpdateGroupTagScopes: vi.fn(),
  useHostTagsWithMeta: vi.fn(),
}))
vi.mock('@/hooks/useUsers', () => ({ useUsers: vi.fn(() => ({ data: undefined })) }))
vi.mock('@/lib/utils/timeFormat', () => ({ formatDateTime: () => '' }))

import { useGroupTagScopes, useHostTagsWithMeta } from '@/hooks/useGroups'
import { EditGroupModal } from '../GroupsSettings'

const GROUP_A = { id: 1, name: 'A', description: '', is_system: false, member_count: 0, created_at: '', updated_at: '' }
const GROUP_B = { ...GROUP_A, id: 2, name: 'B' }

function mockScopes(response: { group_id: number; tag_ids: string[] } | undefined) {
  vi.mocked(useGroupTagScopes).mockReturnValue({ data: response } as ReturnType<typeof useGroupTagScopes>)
}

describe('EditGroupModal host visibility', () => {
  beforeEach(() => {
    vi.mocked(useHostTagsWithMeta).mockReturnValue({ data: TAGS, isLoading: false } as ReturnType<typeof useHostTagsWithMeta>)
  })

  it('does not offer the picker until the group scopes have loaded', () => {
    mockScopes(undefined)
    render(<EditGroupModal group={GROUP_A} isOpen onClose={vi.fn()} onSubmit={vi.fn()} isSubmitting={false} />)
    expect(screen.getByText(/Loading host tags/)).toBeInTheDocument()
    expect(screen.queryByLabelText('dev')).not.toBeInTheDocument()
  })

  it('shows the stored scopes and saves null when untouched', async () => {
    mockScopes({ group_id: 1, tag_ids: ['tag-prod'] })
    const onSubmit = vi.fn()
    render(<EditGroupModal group={GROUP_A} isOpen onClose={vi.fn()} onSubmit={onSubmit} isSubmitting={false} />)
    expect(screen.getByLabelText('prod')).toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: /Save Changes/ }))
    expect(onSubmit).toHaveBeenCalledWith({ name: 'A', description: undefined }, null)
  })

  it('ignores scopes that belong to a different group', () => {
    mockScopes({ group_id: 1, tag_ids: ['tag-prod'] })
    render(<EditGroupModal group={GROUP_B} isOpen onClose={vi.fn()} onSubmit={vi.fn()} isSubmitting={false} />)
    expect(screen.queryByLabelText('prod')).not.toBeInTheDocument()
    expect(screen.getByText(/Loading host tags/)).toBeInTheDocument()
  })

  it('submits the edited selection once touched', async () => {
    mockScopes({ group_id: 1, tag_ids: ['tag-prod'] })
    const onSubmit = vi.fn()
    render(<EditGroupModal group={GROUP_A} isOpen onClose={vi.fn()} onSubmit={onSubmit} isSubmitting={false} />)
    await userEvent.click(screen.getByLabelText('dev'))
    await userEvent.click(screen.getByRole('button', { name: /Save Changes/ }))
    expect(onSubmit).toHaveBeenCalledWith({ name: 'A', description: undefined }, ['tag-prod', 'tag-dev'])
  })
})
