/**
 * Unit tests for StackEditor env-file authoring (issue #205).
 *
 * Regression: env tabs are derived from the stack's env_files map. A new stack
 * (create mode) or an existing stack with no env files must still expose an env
 * editor — a default ".env" tab plus an "Add env file" control — otherwise users
 * can never author environment variables from the editor.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { forwardRef } from 'react'
import { render, screen } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { StackEditor } from './StackEditor'
import * as useStacksModule from '../hooks/useStacks'
import * as useDeploymentsModule from '../hooks/useDeployments'
import * as usePortConflictsModule from '../hooks/usePortConflicts'

vi.mock('../hooks/useStacks')
vi.mock('../hooks/useDeployments')
vi.mock('../hooks/usePortConflicts')

// CodeMirror does not render meaningfully in jsdom; stub the editor.
vi.mock('./ConfigurationEditor', () => ({
  ConfigurationEditor: forwardRef(function MockConfigurationEditor() {
    return <div data-testid="config-editor" />
  }),
}))

const mutation = { mutateAsync: vi.fn(), isPending: false }

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useStacksModule.useStack).mockReturnValue({ data: undefined, isLoading: false } as any)
  vi.mocked(useStacksModule.useCreateStack).mockReturnValue(mutation as any)
  vi.mocked(useStacksModule.useUpdateStack).mockReturnValue(mutation as any)
  vi.mocked(useStacksModule.useRenameStack).mockReturnValue(mutation as any)
  vi.mocked(useStacksModule.useDeleteStack).mockReturnValue(mutation as any)
  vi.mocked(useStacksModule.useCopyStack).mockReturnValue(mutation as any)
  vi.mocked(useDeploymentsModule.useStackAction).mockReturnValue(mutation as any)
  vi.mocked(usePortConflictsModule.usePortConflicts).mockReturnValue({
    conflicts: [],
    isLoading: false,
    error: null,
    recheck: vi.fn(),
  } as any)
})

describe('StackEditor env files', () => {
  it('offers a default .env tab and an add-file control in create mode', () => {
    render(<StackEditor selectedStackName="__new__" hosts={[]} onStackChange={vi.fn()} />)

    expect(screen.getByRole('button', { name: '.env' })).toBeInTheDocument()
    expect(screen.getByTitle('Add env file')).toBeInTheDocument()
  })

  it('adds a new env-file tab through the add dialog', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render(<StackEditor selectedStackName="__new__" hosts={[]} onStackChange={vi.fn()} />)

    await user.click(screen.getByTitle('Add env file'))
    await user.type(screen.getByLabelText('Filename'), '.db.env')
    await user.click(screen.getByRole('button', { name: 'Add File' }))

    expect(screen.getByRole('button', { name: '.db.env' })).toBeInTheDocument()
  })

  it('rejects an unsafe filename in the add dialog', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render(<StackEditor selectedStackName="__new__" hosts={[]} onStackChange={vi.fn()} />)

    await user.click(screen.getByTitle('Add env file'))
    await user.type(screen.getByLabelText('Filename'), 'sub/dir.env')
    await user.click(screen.getByRole('button', { name: 'Add File' }))

    // No tab created; an inline error is shown instead.
    expect(screen.queryByRole('button', { name: 'sub/dir.env' })).not.toBeInTheDocument()
    expect(screen.getByText(/cannot contain spaces or path separators/i)).toBeInTheDocument()
  })
})
