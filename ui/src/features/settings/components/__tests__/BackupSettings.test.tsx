/**
 * BackupSettings - create/download, upload & stage, staged-restore banner, rollback copies.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ApiError } from '@/lib/api/client'
import type { BackupStatus } from '@/types/backup'
import { BackupSettings } from '../BackupSettings'
import * as backupHooks from '@/hooks/useBackup'

vi.mock('@/hooks/useBackup', () => ({
  useBackupStatus: vi.fn(),
  useCreateBackup: vi.fn(),
  useStageBackup: vi.fn(),
  useCancelStagedRestore: vi.fn(),
  useStageRollback: vi.fn(),
  useDeleteRollback: vi.fn(),
  isAllHostsRequired: (error: unknown) => error instanceof ApiError && error.status === 403,
}))
vi.mock('@/features/auth/AuthContext', () => ({ useAuth: () => ({ hasCapability: () => true }) }))
vi.mock('@/lib/hooks/useUserPreferences', () => ({ useTimeFormat: () => ({ timeFormat: '24h' }) }))
vi.mock('@/lib/utils/timeFormat', () => ({ formatDateTime: (value: string) => `fmt(${value})` }))

const EMPTY_STATUS: BackupStatus = { busy: false, pending: null, rollbacks: [], last_restore: null, download: null }

function mutation() {
  return { mutate: vi.fn(), isPending: false }
}

let create: ReturnType<typeof mutation>
let stage: ReturnType<typeof mutation>
let cancel: ReturnType<typeof mutation>
let stageRollback: ReturnType<typeof mutation>
let deleteRollback: ReturnType<typeof mutation>

function setStatus(data: BackupStatus | undefined, error: unknown = null) {
  vi.mocked(backupHooks.useBackupStatus).mockReturnValue({ data, error, isLoading: false } as never)
}

beforeEach(() => {
  create = mutation()
  stage = mutation()
  cancel = mutation()
  stageRollback = mutation()
  deleteRollback = mutation()
  vi.mocked(backupHooks.useCreateBackup).mockReturnValue(create as never)
  vi.mocked(backupHooks.useStageBackup).mockReturnValue(stage as never)
  vi.mocked(backupHooks.useCancelStagedRestore).mockReturnValue(cancel as never)
  vi.mocked(backupHooks.useStageRollback).mockReturnValue(stageRollback as never)
  vi.mocked(backupHooks.useDeleteRollback).mockReturnValue(deleteRollback as never)
  setStatus(EMPTY_STATUS)
})

describe('BackupSettings - create', () => {
  it('blocks a short passphrase', async () => {
    render(<BackupSettings />)
    await userEvent.type(screen.getByLabelText('Backup passphrase'), 'short')
    await userEvent.type(screen.getByLabelText('Repeat passphrase'), 'short')
    expect(screen.getByRole('button', { name: /download backup/i })).toBeDisabled()
    expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument()
  })

  it('blocks mismatched passphrases', async () => {
    render(<BackupSettings />)
    await userEvent.type(screen.getByLabelText('Backup passphrase'), 'correct horse')
    await userEvent.type(screen.getByLabelText('Repeat passphrase'), 'correct house')
    expect(screen.getByRole('button', { name: /download backup/i })).toBeDisabled()
    expect(screen.getByText(/do not match/i)).toBeInTheDocument()
  })

  it('creates a backup with stats history by default', async () => {
    render(<BackupSettings />)
    await userEvent.type(screen.getByLabelText('Backup passphrase'), 'correct horse')
    await userEvent.type(screen.getByLabelText('Repeat passphrase'), 'correct horse')
    await userEvent.click(screen.getByRole('button', { name: /download backup/i }))
    expect(create.mutate).toHaveBeenCalledWith({ passphrase: 'correct horse', include_stats: true }, expect.anything())
  })
})

describe('BackupSettings - restore', () => {
  it('asks for confirmation before staging', async () => {
    render(<BackupSettings />)
    const file = new File(['x'], 'dockmon.dmbak', { type: 'application/octet-stream' })
    await userEvent.upload(screen.getByLabelText('Backup file'), file)
    await userEvent.type(screen.getByLabelText('Passphrase of this backup'), 'correct horse')
    await userEvent.click(screen.getByRole('button', { name: /validate & stage/i }))
    expect(stage.mutate).not.toHaveBeenCalled()

    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/left as they are/i)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: /stage restore/i }))
    expect(stage.mutate).toHaveBeenCalledWith(
      { file, passphrase: 'correct horse', replace: false },
      expect.anything(),
    )
  })

  it('shows a staged restore with restart instructions and cancel', async () => {
    setStatus({
      ...EMPTY_STATUS,
      pending: {
        created_at: '2026-09-25T10:00:00Z',
        app_version: '2.5.1',
        alembic_revision: '046_group_tag_scopes',
        stats_history_included: true,
        summary: { hosts: 5, users: 7, alert_rules: 2, stacks: ['homepage', 'keycloak'] },
      },
    })
    render(<BackupSettings />)
    expect(screen.getByText(/docker restart dockmon/)).toBeInTheDocument()
    expect(screen.getByText(/5 hosts/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /cancel staged restore/i }))
    expect(cancel.mutate).toHaveBeenCalled()
  })
})

describe('BackupSettings - access', () => {
  it('explains that backup needs access to all hosts', () => {
    setStatus(undefined, new ApiError('Backup and restore require access to all hosts', 403))
    render(<BackupSettings />)
    expect(screen.getByText(/need access to all hosts/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /download backup/i })).not.toBeInTheDocument()
  })
})

describe('BackupSettings - rollback copies', () => {
  it('deletes a rollback copy only after confirming', async () => {
    setStatus({
      ...EMPTY_STATUS,
      rollbacks: [{ id: '20260925T191443770843Z', created_at: '2026-09-25T19:14:43Z', replaced_by_backup_created_at: null }],
    })
    render(<BackupSettings />)
    await userEvent.click(screen.getByRole('button', { name: /delete rollback copy/i }))
    expect(deleteRollback.mutate).not.toHaveBeenCalled()
    const dialog = await screen.findByRole('alertdialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /^delete$/i }))
    expect(deleteRollback.mutate).toHaveBeenCalledWith('20260925T191443770843Z')
  })
})
