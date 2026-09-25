import { useState } from 'react'
import { AlertTriangle, Download, RotateCcw, Trash2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  backupDownloadUrl,
  isAllHostsRequired,
  useBackupStatus,
  useCancelStagedRestore,
  useCreateBackup,
  useDeleteRollback,
  useStageBackup,
  useStageRollback,
} from '@/hooks/useBackup'
import { useTimeFormat } from '@/lib/hooks/useUserPreferences'
import { pluralize } from '@/lib/utils/formatting'
import { formatDateTime } from '@/lib/utils/timeFormat'
import type { BackupDownload, BackupManifestSummary, RollbackCopy } from '@/types/backup'
import { ToggleSwitch } from './ToggleSwitch'

const MIN_PASSPHRASE_LENGTH = 8
const INPUT_CLASS =
  'w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500'

function plural(count: number, noun: string): string {
  return `${count} ${pluralize(count, noun)}`
}

function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <h3 className="text-lg font-semibold text-white">{title}</h3>
      <p className="mt-1 text-xs text-gray-400">{description}</p>
    </div>
  )
}

function CreateBackupSection({ busy }: { busy: boolean }) {
  const createBackup = useCreateBackup()
  const [passphrase, setPassphrase] = useState('')
  const [repeat, setRepeat] = useState('')
  const [includeStats, setIncludeStats] = useState(true)

  const tooShort = passphrase.length > 0 && passphrase.length < MIN_PASSPHRASE_LENGTH
  const mismatch = repeat.length > 0 && passphrase !== repeat
  const canSubmit =
    passphrase.length >= MIN_PASSPHRASE_LENGTH && passphrase === repeat && !createBackup.isPending && !busy

  const handleCreate = () => {
    createBackup.mutate(
      { passphrase, include_stats: includeStats },
      {
        onSuccess: () => {
          setPassphrase('')
          setRepeat('')
        },
      },
    )
  }

  return (
    <div>
      <SectionHeader
        title="Create Backup"
        description="Downloads an encrypted file with DockMon's database and the compose/.env files of its stacks. Container data and volumes are not included."
      />
      <div className="space-y-4">
        <div className="flex items-start gap-2 rounded-md border border-yellow-800/60 bg-yellow-900/20 p-3 text-xs text-yellow-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <span>
            The backup contains the DockMon database with every stored credential, plus the encryption key. Keep the
            passphrase somewhere safe: it cannot be recovered, and the backup is useless without it.
          </span>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="backup-passphrase" className="mb-2 block text-sm font-medium text-gray-300">
              Backup passphrase
            </label>
            <input
              id="backup-passphrase"
              type="password"
              autoComplete="new-password"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
              className={INPUT_CLASS}
            />
          </div>
          <div>
            <label htmlFor="backup-passphrase-repeat" className="mb-2 block text-sm font-medium text-gray-300">
              Repeat passphrase
            </label>
            <input
              id="backup-passphrase-repeat"
              type="password"
              autoComplete="new-password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              className={INPUT_CLASS}
            />
          </div>
        </div>
        {tooShort && <p className="text-xs text-red-400">The passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters.</p>}
        {mismatch && <p className="text-xs text-red-400">The passphrases do not match.</p>}
        <ToggleSwitch
          id="backup-include-stats"
          label="Include stats history"
          description="CPU, memory and network history. Leave it out for a smaller backup."
          checked={includeStats}
          onChange={setIncludeStats}
        />
        <Button onClick={handleCreate} disabled={!canSubmit}>
          <Download className="mr-2 h-4 w-4" />
          {createBackup.isPending ? 'Creating backup…' : 'Download backup'}
        </Button>
      </div>
    </div>
  )
}

function StagedRestoreBanner({ pending }: { pending: BackupManifestSummary }) {
  const cancel = useCancelStagedRestore()
  const { timeFormat } = useTimeFormat()
  const { summary } = pending
  return (
    <div className="rounded-md border border-blue-800/60 bg-blue-900/20 p-4 text-sm text-blue-100">
      <p className="font-medium text-white">A restore is staged</p>
      <p className="mt-1">
        Backup from {formatDateTime(pending.created_at, timeFormat)} (DockMon {pending.app_version}):{' '}
        {plural(summary.hosts, 'host')}, {plural(summary.users, 'user')}, {plural(summary.alert_rules, 'alert rule')},{' '}
        {plural(summary.stacks.length, 'stack')}
        {pending.stats_history_included ? '' : ', without stats history'}.
      </p>
      <p className="mt-2">
        Restart DockMon to apply it: <code className="rounded bg-gray-900 px-1.5 py-0.5">docker restart dockmon</code>.
        Everyone will be signed out.
      </p>
      <Button variant="outline" size="sm" className="mt-3" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
        Cancel staged restore
      </Button>
    </div>
  )
}

function RestoreSection({ busy, hasPending }: { busy: boolean; hasPending: boolean }) {
  const stage = useStageBackup()
  const [file, setFile] = useState<File | null>(null)
  const [passphrase, setPassphrase] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)

  const canSubmit = file !== null && passphrase.length > 0 && !stage.isPending && !busy

  const handleStage = () => {
    if (!file) return
    setConfirmOpen(false)
    stage.mutate(
      { file, passphrase, replace: hasPending },
      {
        onSuccess: () => {
          setFile(null)
          setPassphrase('')
        },
      },
    )
  }

  return (
    <div>
      <SectionHeader
        title="Restore from Backup"
        description="The backup is decrypted and fully validated first; nothing changes until DockMon restarts."
      />
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="restore-file" className="mb-2 block text-sm font-medium text-gray-300">
              Backup file
            </label>
            <input
              id="restore-file"
              type="file"
              accept=".dmbak"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-gray-300 file:mr-3 file:rounded-md file:border-0 file:bg-gray-700 file:px-3 file:py-2 file:text-sm file:text-white"
            />
          </div>
          <div>
            <label htmlFor="restore-passphrase" className="mb-2 block text-sm font-medium text-gray-300">
              Passphrase of this backup
            </label>
            <input
              id="restore-passphrase"
              type="password"
              autoComplete="off"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
              className={INPUT_CLASS}
            />
          </div>
        </div>
        <Button onClick={() => setConfirmOpen(true)} disabled={!canSubmit}>
          <Upload className="mr-2 h-4 w-4" />
          {stage.isPending ? 'Uploading and validating…' : 'Validate & stage'}
        </Button>
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Restore DockMon from this backup?</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2">
                <p>
                  On the next restart, DockMon&apos;s database is replaced by the backup: settings, hosts, users, groups,
                  credentials and alert rules. The compose/.env files of the stacks in the backup are replaced too.
                </p>
                <p>
                  Stacks that exist only on this install, and all container data and volumes, are left as they are.
                  The current state is kept as a rollback copy.
                </p>
                {hasPending && <p>This replaces the restore that is already staged.</p>}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleStage}>Stage restore</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function RollbackCopiesSection({ rollbacks }: { rollbacks: RollbackCopy[] }) {
  const stageRollback = useStageRollback()
  const deleteRollback = useDeleteRollback()
  const { timeFormat } = useTimeFormat()
  const [toDelete, setToDelete] = useState<string | null>(null)

  if (rollbacks.length === 0) return null

  return (
    <div>
      <SectionHeader
        title="Rollback Copies"
        description="The state a restore replaced. It holds the old database and encryption key unencrypted; delete it once the restore is confirmed good."
      />
      <ul className="divide-y divide-gray-800 rounded-md border border-gray-800">
        {rollbacks.map((rollback) => (
          <li key={rollback.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
            <span className="text-gray-300">
              Taken {rollback.created_at ? formatDateTime(rollback.created_at, timeFormat) : rollback.id}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => stageRollback.mutate(rollback.id)}
                disabled={stageRollback.isPending}
                aria-label="Stage rollback copy"
              >
                <RotateCcw className="mr-1 h-4 w-4" />
                Stage
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setToDelete(rollback.id)}
                disabled={deleteRollback.isPending}
                aria-label="Delete rollback copy"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </li>
        ))}
      </ul>

      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete rollback copy?</AlertDialogTitle>
            <AlertDialogDescription>
              You will no longer be able to return to the state before that restore. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete) deleteRollback.mutate(toDelete)
                setToDelete(null)
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function LatestDownload({ download }: { download: BackupDownload }) {
  const { timeFormat } = useTimeFormat()
  return (
    <p className="text-xs text-gray-400">
      Latest backup:{' '}
      <a href={backupDownloadUrl(download.download_id)} download={download.filename} className="text-blue-400 underline">
        {download.filename}
      </a>{' '}
      (link valid until {formatDateTime(download.expires_at, timeFormat)})
    </p>
  )
}

export function BackupSettings() {
  const { data: status, error, isLoading, refetch } = useBackupStatus()
  const { timeFormat } = useTimeFormat()

  if (isAllHostsRequired(error)) {
    return (
      <p className="text-sm text-gray-400">
        Backup and restore need access to all hosts. Your groups are limited to some hosts by tag.
      </p>
    )
  }
  if (error) {
    return (
      <div className="space-y-3 text-sm text-gray-400">
        <p>Could not load backup status: {error.message}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          Retry
        </Button>
      </div>
    )
  }
  if (isLoading || !status) {
    return <p className="text-sm text-gray-400">Loading…</p>
  }

  const lastRestore = status.last_restore
  return (
    <div className="space-y-8">
      {status.pending && <StagedRestoreBanner pending={status.pending} />}
      {lastRestore?.restored_at && (
        <p className="text-xs text-gray-400">
          Last restore: {formatDateTime(lastRestore.restored_at, timeFormat)}
          {lastRestore.backup?.created_at &&
            `, from a backup made ${formatDateTime(lastRestore.backup.created_at, timeFormat)}`}
          {lastRestore.initiated_by && ` (by ${lastRestore.initiated_by})`}.
        </p>
      )}
      {status.busy && <p className="text-xs text-gray-400">A backup or restore operation is running…</p>}
      {status.download && <LatestDownload download={status.download} />}
      <CreateBackupSection busy={status.busy} />
      <RestoreSection busy={status.busy} hasPending={status.pending !== null} />
      <RollbackCopiesSection rollbacks={status.rollbacks} />
    </div>
  )
}
