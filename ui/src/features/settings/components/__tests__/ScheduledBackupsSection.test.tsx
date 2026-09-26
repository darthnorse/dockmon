/**
 * ScheduledBackupsSection - schedule settings, destination warnings, run now, scheduled files.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { BackupSchedule, ScheduledBackupFiles } from '@/types/backup'
import { ScheduledBackupsSection } from '../ScheduledBackupsSection'
import * as backupHooks from '@/hooks/useBackup'

vi.mock('@/hooks/useBackup', () => ({
  useBackupSchedule: vi.fn(),
  useUpdateBackupSchedule: vi.fn(),
  useRunScheduledBackup: vi.fn(),
  useScheduledFiles: vi.fn(),
  useDeleteScheduledFile: vi.fn(),
  useStageScheduledFile: vi.fn(),
  scheduledFileUrl: (name: string) => `/api/v2/backup/files/${name}`,
}))
vi.mock('@/lib/hooks/useUserPreferences', () => ({ useTimeFormat: () => ({ timeFormat: '24h' }) }))
vi.mock('@/lib/utils/timeFormat', () => ({ formatDateTime: (value: string) => `fmt(${value})` }))

const FILE = 'dockmon-scheduled-1a2b3c4d-20260925T030000.000000Z-abcd-2.5.1.dmbak'

const SCHEDULE: BackupSchedule = {
  enabled: true,
  schedule: '03:00',
  retention: 7,
  include_stats: true,
  passphrase_set: true,
  last_run_at: '2026-09-25T03:00:00Z',
  last_status: 'ok',
  last_error: null,
  last_file: FILE,
  next_run_at: '2026-09-26T03:00:00Z',
  timezone: 'Europe/Oslo',
  timezone_error: null,
  destination: {
    path: '/backups',
    exists: true,
    is_mountpoint: true,
    writable: true,
    same_filesystem_as_data: false,
    free_bytes: 10_000_000_000,
  },
}

const FILES: ScheduledBackupFiles = { files: [{ name: FILE, size: 1655976, created_at: '2026-09-25T03:00:00Z' }], other_backups: 0 }

function mutation() {
  return { mutate: vi.fn(), isPending: false }
}

let update: ReturnType<typeof mutation>
let run: ReturnType<typeof mutation>
let del: ReturnType<typeof mutation>
let stage: ReturnType<typeof mutation>

function setSchedule(data: BackupSchedule) {
  vi.mocked(backupHooks.useBackupSchedule).mockReturnValue({ data, error: null, isLoading: false, refetch: vi.fn() } as never)
}

beforeEach(() => {
  update = mutation()
  run = mutation()
  del = mutation()
  stage = mutation()
  vi.mocked(backupHooks.useUpdateBackupSchedule).mockReturnValue(update as never)
  vi.mocked(backupHooks.useRunScheduledBackup).mockReturnValue(run as never)
  vi.mocked(backupHooks.useDeleteScheduledFile).mockReturnValue(del as never)
  vi.mocked(backupHooks.useStageScheduledFile).mockReturnValue(stage as never)
  vi.mocked(backupHooks.useScheduledFiles).mockReturnValue({ data: FILES, refetch: vi.fn() } as never)
  setSchedule(SCHEDULE)
})

describe('ScheduledBackupsSection - settings', () => {
  it('saves only the changed fields and never shows the stored passphrase', async () => {
    render(<ScheduledBackupsSection />)
    const retention = screen.getByLabelText('Keep this many backups')
    await userEvent.clear(retention)
    await userEvent.type(retention, '14')
    expect(screen.getByLabelText('Scheduled backup passphrase')).toHaveValue('')
    await userEvent.click(screen.getByRole('button', { name: /save schedule/i }))
    expect(update.mutate).toHaveBeenCalledWith({ retention: 14 }, expect.anything())
  })

  it('needs a passphrase before scheduling can be enabled', async () => {
    setSchedule({ ...SCHEDULE, enabled: false, passphrase_set: false })
    render(<ScheduledBackupsSection />)
    await userEvent.click(screen.getByRole('switch', { name: /enable scheduled backups/i }))
    expect(screen.getByRole('button', { name: /save schedule/i })).toBeDisabled()
    expect(screen.getByText(/set a passphrase/i)).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Scheduled backup passphrase'), 'nas-backup-pass')
    await userEvent.type(screen.getByLabelText('Repeat scheduled passphrase'), 'nas-backup-pass')
    await userEvent.click(screen.getByRole('button', { name: /save schedule/i }))
    expect(update.mutate).toHaveBeenCalledWith({ enabled: true, passphrase: 'nas-backup-pass' }, expect.anything())
  })

  it('shows the last failure', () => {
    setSchedule({ ...SCHEDULE, last_status: 'failed', last_error: 'The backup destination does not exist' })
    render(<ScheduledBackupsSection />)
    expect(screen.getByText('The backup destination does not exist')).toBeInTheDocument()
  })
})

describe('ScheduledBackupsSection - destination', () => {
  it('warns when /backups is not a mount', () => {
    setSchedule({ ...SCHEDULE, destination: { ...SCHEDULE.destination, is_mountpoint: false } })
    render(<ScheduledBackupsSection />)
    expect(screen.getByText(/not a mounted volume/i)).toBeInTheDocument()
  })

  it('warns when /backups is on the same filesystem as DockMon data', () => {
    setSchedule({ ...SCHEDULE, destination: { ...SCHEDULE.destination, same_filesystem_as_data: true } })
    render(<ScheduledBackupsSection />)
    expect(screen.getByText(/same filesystem/i)).toBeInTheDocument()
  })

  it('explains a missing destination', () => {
    setSchedule({ ...SCHEDULE, destination: { ...SCHEDULE.destination, exists: false } })
    render(<ScheduledBackupsSection />)
    expect(screen.getByText(/does not exist/i)).toBeInTheDocument()
  })
})

describe('ScheduledBackupsSection - actions', () => {
  it('runs a backup now', async () => {
    render(<ScheduledBackupsSection />)
    await userEvent.click(screen.getByRole('button', { name: /run now/i }))
    expect(run.mutate).toHaveBeenCalled()
  })

  it('deletes a scheduled file only after confirming', async () => {
    render(<ScheduledBackupsSection />)
    await userEvent.click(screen.getByRole('button', { name: /delete backup file/i }))
    expect(del.mutate).not.toHaveBeenCalled()
    const dialog = await screen.findByRole('alertdialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /^delete$/i }))
    expect(del.mutate).toHaveBeenCalledWith(FILE)
  })

  it('stages a restore from a scheduled file with its passphrase', async () => {
    render(<ScheduledBackupsSection />)
    await userEvent.click(screen.getByRole('button', { name: /restore from this file/i }))
    const dialog = await screen.findByRole('alertdialog')
    await userEvent.type(within(dialog).getByLabelText('Passphrase of this backup'), 'nas-backup-pass')
    await userEvent.click(within(dialog).getByRole('button', { name: /stage restore/i }))
    expect(stage.mutate).toHaveBeenCalledWith({ name: FILE, passphrase: 'nas-backup-pass', replace: false })
  })
})
