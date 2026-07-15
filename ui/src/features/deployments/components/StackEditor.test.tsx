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
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { StackEditor, blockingComposeErrorMessage } from './StackEditor'
import { ApiError } from '@/lib/api/client'
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
const deleteEnvFileMock = { mutateAsync: vi.fn().mockResolvedValue({ deleted: true }), isPending: false }

beforeEach(() => {
  vi.clearAllMocks()
  deleteEnvFileMock.mutateAsync.mockResolvedValue({ deleted: true })
  vi.mocked(useStacksModule.useStack).mockReturnValue({ data: undefined, isLoading: false } as any)
  vi.mocked(useStacksModule.useCreateStack).mockReturnValue(mutation as any)
  vi.mocked(useStacksModule.useUpdateStack).mockReturnValue(mutation as any)
  vi.mocked(useStacksModule.useRenameStack).mockReturnValue(mutation as any)
  vi.mocked(useStacksModule.useDeleteStack).mockReturnValue(mutation as any)
  vi.mocked(useStacksModule.useCopyStack).mockReturnValue(mutation as any)
  vi.mocked(useStacksModule.useDeleteEnvFile).mockReturnValue(deleteEnvFileMock as any)
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

describe('StackEditor remove env file', () => {
  it('shows a × button for a session-added env tab, clicking it opens the confirm dialog', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render(<StackEditor selectedStackName="__new__" hosts={[]} onStackChange={vi.fn()} />)

    // Add .db.env via the add flow
    await user.click(screen.getByTitle('Add env file'))
    await user.type(screen.getByLabelText('Filename'), '.db.env')
    await user.click(screen.getByRole('button', { name: 'Add File' }))

    // The × button should appear for the newly-added tab
    expect(screen.getByTitle('Remove .db.env')).toBeInTheDocument()

    // Clicking it should open the confirm dialog for an unsaved file
    await user.click(screen.getByTitle('Remove .db.env'))
    expect(screen.getByRole('button', { name: 'Remove file' })).toBeInTheDocument()
  })

  it('confirming removal of an unsaved added file drops the tab with no delete call', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render(<StackEditor selectedStackName="__new__" hosts={[]} onStackChange={vi.fn()} />)

    // Add .db.env via the add flow
    await user.click(screen.getByTitle('Add env file'))
    await user.type(screen.getByLabelText('Filename'), '.db.env')
    await user.click(screen.getByRole('button', { name: 'Add File' }))

    // Open the remove dialog
    await user.click(screen.getByTitle('Remove .db.env'))

    // Confirm removal
    await user.click(screen.getByRole('button', { name: 'Remove file' }))

    // Tab should be gone; no backend call
    expect(screen.queryByRole('button', { name: '.db.env' })).not.toBeInTheDocument()
    expect(deleteEnvFileMock.mutateAsync).not.toHaveBeenCalled()
  })

  it('confirming removal of a persisted file calls the delete mutation and drops the tab', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    vi.mocked(useStacksModule.useStack).mockReturnValue({
      data: { name: 'myapp', compose_yaml: 'services: {}\n', env_files: { '.db.env': 'A=1' }, deployed_to: [] },
      isLoading: false,
    } as any)

    render(<StackEditor selectedStackName="myapp" hosts={[]} onStackChange={vi.fn()} />)

    // The .db.env tab should be loaded from the persisted stack
    expect(screen.getByRole('button', { name: '.db.env' })).toBeInTheDocument()

    // Click the × button — dialog should show "Delete file" (persisted)
    await user.click(screen.getByTitle('Remove .db.env'))
    expect(screen.getByRole('button', { name: 'Delete file' })).toBeInTheDocument()

    // Confirm deletion
    await user.click(screen.getByRole('button', { name: 'Delete file' }))

    // Backend should be called and tab should be gone
    await waitFor(() => {
      expect(deleteEnvFileMock.mutateAsync).toHaveBeenCalledWith({ name: 'myapp', filename: '.db.env' })
      expect(screen.queryByRole('button', { name: '.db.env' })).not.toBeInTheDocument()
    })
  })

  it('the virtual default .env placeholder shows no × button', () => {
    render(<StackEditor selectedStackName="__new__" hosts={[]} onStackChange={vi.fn()} />)

    // The .env tab should be present as a tab button
    expect(screen.getByRole('button', { name: '.env' })).toBeInTheDocument()

    // But there should be no × button for the virtual .env
    expect(screen.queryByTitle('Remove .env')).not.toBeInTheDocument()
  })
})

describe('StackEditor load-effect guard', () => {
  it('does not reset editor state when the same stack refetches in the background', () => {
    vi.mocked(useStacksModule.useStack).mockReturnValue({
      data: { name: 'myapp', compose_yaml: 'services: {}\n', env_files: { '.db.env': 'A=1' }, deployed_to: [] },
      isLoading: false,
    } as any)
    const { rerender } = render(<StackEditor selectedStackName="myapp" hosts={[]} onStackChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: '.db.env' })).toBeInTheDocument()

    // Simulate a background refetch for the SAME stack returning a different env set.
    vi.mocked(useStacksModule.useStack).mockReturnValue({
      data: { name: 'myapp', compose_yaml: 'services: {}\n', env_files: {}, deployed_to: [] },
      isLoading: false,
    } as any)
    rerender(<StackEditor selectedStackName="myapp" hosts={[]} onStackChange={vi.fn()} />)

    // Guard: load effect must NOT re-run for the same identity; local state preserved.
    expect(screen.getByRole('button', { name: '.db.env' })).toBeInTheDocument()
  })

  it('reloads editor state when switching to a different stack', () => {
    vi.mocked(useStacksModule.useStack).mockReturnValue({
      data: { name: 'myapp', compose_yaml: 'services: {}\n', env_files: { '.db.env': 'A=1' }, deployed_to: [] },
      isLoading: false,
    } as any)
    const { rerender } = render(<StackEditor selectedStackName="myapp" hosts={[]} onStackChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: '.db.env' })).toBeInTheDocument()

    vi.mocked(useStacksModule.useStack).mockReturnValue({
      data: { name: 'other', compose_yaml: 'services: {}\n', env_files: { '.other.env': 'B=2' }, deployed_to: [] },
      isLoading: false,
    } as any)
    rerender(<StackEditor selectedStackName="other" hosts={[]} onStackChange={vi.fn()} />)

    expect(screen.queryByRole('button', { name: '.db.env' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '.other.env' })).toBeInTheDocument()
  })
})

describe('StackEditor unreferenced env badge', () => {
  const stackWithUnreferenced = {
    name: 'myapp',
    deployed_to: [],
    compose_yaml: 'services:\n  app:\n    image: x\n',
    env_files: { '.env': 'A=1', '.db.env': 'P=2', '.env.staging': 'S=3' },
    referenced_env_files: ['.env', '.db.env'],
  }

  it('badges a discovered unreferenced tab but not referenced tabs', async () => {
    vi.mocked(useStacksModule.useStack).mockReturnValue({
      data: stackWithUnreferenced,
      isLoading: false,
    } as any)

    render(<StackEditor selectedStackName="myapp" hosts={[]} onStackChange={vi.fn()} />)

    // The unreferenced .env.staging tab carries the "not referenced" badge.
    const badge = await screen.findByTitle(/not referenced by your compose/i)
    expect(badge).toBeInTheDocument()

    // Exactly one badge: .env and .db.env (referenced) do not get one.
    expect(screen.getAllByTitle(/not referenced by your compose/i)).toHaveLength(1)
  })

  it('shows no unref badge in create mode, even for an added env file', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render(<StackEditor selectedStackName="__new__" hosts={[]} onStackChange={vi.fn()} />)

    // Add a non-.env tab; in create mode it must NOT be badged (no running stack
    // exists to reference anything yet), even though it isn't "referenced".
    await user.click(screen.getByTitle('Add env file'))
    await user.type(screen.getByLabelText('Filename'), '.db.env')
    await user.click(screen.getByRole('button', { name: 'Add File' }))

    expect(screen.getByRole('button', { name: '.db.env' })).toBeInTheDocument()
    expect(screen.queryByTitle(/not referenced by your compose/i)).not.toBeInTheDocument()
  })
})

describe('StackEditor deploy guard (discussion #236)', () => {
  it('does not deploy when the pre-deploy port check reports a malformed compose (400)', async () => {
    const user = userEvent.setup()
    vi.mocked(useStacksModule.useStack).mockReturnValue({
      data: { name: 'myapp', compose_yaml: 'services: {}\n', env_files: {}, deployed_to: [] },
      isLoading: false,
    } as any)
    const composeErr = new ApiError('Compose file has a tab character at line 2, column 1.', 400)
    const recheck = vi.fn().mockRejectedValue(composeErr)
    vi.mocked(usePortConflictsModule.usePortConflicts).mockReturnValue({
      conflicts: [], isLoading: false, error: null, recheck,
    } as any)

    // A single host auto-selects, enabling the Deploy button.
    const hosts = [{ id: 'host-1', name: 'prod', status: 'online' }]
    render(<StackEditor selectedStackName="myapp" hosts={hosts as any} onStackChange={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: /deploy/i }))

    await waitFor(() => expect(recheck).toHaveBeenCalled())
    // The bad compose must block the deploy, not fall through to executeDeploy().
    expect(useDeploymentsModule.useStackAction().mutateAsync).not.toHaveBeenCalled()
  })

  it('deploys anyway when the port check fails for a non-compose reason (host unreachable)', async () => {
    const user = userEvent.setup()
    vi.mocked(useStacksModule.useStack).mockReturnValue({
      data: { name: 'myapp', compose_yaml: 'services: {}\n', env_files: {}, deployed_to: [] },
      isLoading: false,
    } as any)
    const recheck = vi.fn().mockRejectedValue(new ApiError('Host not available for port check', 409))
    vi.mocked(usePortConflictsModule.usePortConflicts).mockReturnValue({
      conflicts: [], isLoading: false, error: null, recheck,
    } as any)

    const hosts = [{ id: 'host-1', name: 'prod', status: 'online' }]
    render(<StackEditor selectedStackName="myapp" hosts={hosts as any} onStackChange={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: /deploy/i }))

    await waitFor(() => expect(useDeploymentsModule.useStackAction().mutateAsync).toHaveBeenCalled())
  })
})

describe('blockingComposeErrorMessage', () => {
  const err = new ApiError('Compose file has a tab character at line 2, column 1.', 400)

  it('returns the message for a 400 when there are no unsaved changes', () => {
    expect(blockingComposeErrorMessage(err, false)).toBe(err.message)
  })

  it('returns null for a 400 when there ARE unsaved changes (let save-first flow run)', () => {
    // A user who fixed a malformed saved stack in the editor must not be blocked;
    // the deploy falls through to the save-changes dialog which re-validates.
    expect(blockingComposeErrorMessage(err, true)).toBeNull()
  })

  it('returns null for a non-400 error (host unreachable)', () => {
    expect(blockingComposeErrorMessage(new ApiError('offline', 409), false)).toBeNull()
  })

  it('returns null for a non-ApiError', () => {
    expect(blockingComposeErrorMessage(new Error('boom'), false)).toBeNull()
  })
})
