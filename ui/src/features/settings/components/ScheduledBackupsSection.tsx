import { useState } from 'react'
import { AlertTriangle, Download, Play, RefreshCw, RotateCcw, Trash2 } from 'lucide-react'
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
  scheduledFileUrl,
  useBackupSchedule,
  useDeleteScheduledFile,
  useRunScheduledBackup,
  useScheduledFiles,
  useStageScheduledFile,
  useUpdateBackupSchedule,
} from '@/hooks/useBackup'
import { useTimeFormat } from '@/lib/hooks/useUserPreferences'
import { formatBytes } from '@/lib/utils/formatting'
import { formatDateTime } from '@/lib/utils/timeFormat'
import type { BackupDestination, BackupSchedule, BackupScheduleUpdate } from '@/types/backup'
import { INPUT_CLASS, MIN_PASSPHRASE_LENGTH } from './backupForm'
import { ToggleSwitch } from './ToggleSwitch'


function DestinationWarnings({ destination }: { destination: BackupDestination }) {
  const warnings: string[] = []
  if (!destination.responding) {
    warnings.push(`${destination.path} is not responding. Check the NAS or the mount.`)
  } else if (!destination.exists) {
    warnings.push(`${destination.path} does not exist in the container. Mount a NAS share or another disk there.`)
  } else {
    if (!destination.is_mountpoint) {
      warnings.push(
        `${destination.path} is not a mounted volume, so backups would be lost with the container. Scheduled runs will fail until it is mounted.`,
      )
    }
    if (!destination.writable) warnings.push(`DockMon cannot write to ${destination.path}.`)
    if (destination.same_filesystem_as_data) {
      warnings.push(
        `${destination.path} is on the same filesystem as DockMon's data, so a disk failure would take both. Prefer a NAS or another disk.`,
      )
    }
  }
  if (warnings.length === 0) return null
  return (
    <div className="space-y-1 rounded-md border border-yellow-800/60 bg-yellow-900/20 p-3 text-xs text-yellow-200">
      {warnings.map((warning) => (
        <p key={warning} className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          {warning}
        </p>
      ))}
    </div>
  )
}

function changedFields(
  saved: BackupSchedule,
  form: { enabled: boolean; schedule: string; retention: string; includeStats: boolean },
  passphrase: string,
): BackupScheduleUpdate {
  const update: BackupScheduleUpdate = {}
  if (form.enabled !== saved.enabled) update.enabled = form.enabled
  if (form.schedule.trim() !== saved.schedule) update.schedule = form.schedule.trim()
  if (Number(form.retention) !== saved.retention) update.retention = Number(form.retention)
  if (form.includeStats !== saved.include_stats) update.include_stats = form.includeStats
  if (passphrase) update.passphrase = passphrase
  return update
}

function ScheduleForm({ saved }: { saved: BackupSchedule }) {
  const update = useUpdateBackupSchedule()
  const [enabled, setEnabled] = useState(saved.enabled)
  const [schedule, setSchedule] = useState(saved.schedule)
  const [retention, setRetention] = useState(String(saved.retention))
  const [includeStats, setIncludeStats] = useState(saved.include_stats)
  const [passphrase, setPassphrase] = useState('')
  const [repeat, setRepeat] = useState('')

  const passphraseTooShort = passphrase.length > 0 && passphrase.length < MIN_PASSPHRASE_LENGTH
  const passphraseMismatch = repeat.length > 0 && passphrase !== repeat
  const needsPassphrase = enabled && !saved.passphrase_set && passphrase.length === 0
  const changes = changedFields(saved, { enabled, schedule, retention, includeStats }, passphrase)
  const canSave =
    Object.keys(changes).length > 0 &&
    !passphraseTooShort &&
    passphrase === repeat &&
    !needsPassphrase &&
    !update.isPending

  const handleSave = () => {
    update.mutate(changes, {
      onSuccess: () => {
        setPassphrase('')
        setRepeat('')
      },
    })
  }

  return (
    <div className="space-y-4">
      <ToggleSwitch
        id="backup-schedule-enabled"
        label="Enable scheduled backups"
        description="Write an encrypted backup on a schedule and keep the newest ones."
        checked={enabled}
        onChange={setEnabled}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="backup-schedule" className="mb-2 block text-sm font-medium text-gray-300">
            When
          </label>
          <input id="backup-schedule" value={schedule} onChange={(e) => setSchedule(e.target.value)} className={INPUT_CLASS} />
          <p className="mt-1 text-xs text-gray-400">
            HH:MM daily, or a 5-field cron expression, in {saved.timezone}.
            {saved.timezone_error && <span className="block text-yellow-300">{saved.timezone_error}</span>}
          </p>
        </div>
        <div>
          <label htmlFor="backup-retention" className="mb-2 block text-sm font-medium text-gray-300">
            Keep this many backups
          </label>
          <input
            id="backup-retention"
            type="number"
            min={1}
            max={365}
            value={retention}
            onChange={(e) => setRetention(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
      </div>
      <ToggleSwitch
        id="backup-schedule-stats"
        label="Include stats history"
        checked={includeStats}
        onChange={setIncludeStats}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="backup-schedule-passphrase" className="mb-2 block text-sm font-medium text-gray-300">
            Scheduled backup passphrase
          </label>
          <input
            id="backup-schedule-passphrase"
            type="password"
            autoComplete="new-password"
            placeholder={saved.passphrase_set ? 'Stored; leave empty to keep it' : ''}
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor="backup-schedule-passphrase-repeat" className="mb-2 block text-sm font-medium text-gray-300">
            Repeat scheduled passphrase
          </label>
          <input
            id="backup-schedule-passphrase-repeat"
            type="password"
            autoComplete="new-password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
      </div>
      <p className="text-xs text-gray-400">
        Stored encrypted in DockMon. You need it to restore these backups, so keep a copy elsewhere. Changing it does
        not re-encrypt existing backups.
      </p>
      {needsPassphrase && <p className="text-xs text-red-400">Set a passphrase before enabling scheduled backups.</p>}
      {passphraseTooShort && (
        <p className="text-xs text-red-400">The passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters.</p>
      )}
      {passphraseMismatch && <p className="text-xs text-red-400">The passphrases do not match.</p>}
      <Button onClick={handleSave} disabled={!canSave}>
        {update.isPending ? 'Saving…' : 'Save schedule'}
      </Button>
    </div>
  )
}

function ScheduledFiles() {
  const { data } = useScheduledFiles()
  const deleteFile = useDeleteScheduledFile()
  const stageFile = useStageScheduledFile()
  const { timeFormat } = useTimeFormat()
  const [toDelete, setToDelete] = useState<string | null>(null)
  const [toStage, setToStage] = useState<string | null>(null)
  const [stagePassphrase, setStagePassphrase] = useState('')

  if (!data || (data.files.length === 0 && data.other_backups === 0)) return null

  return (
    <div className="space-y-2">
      <ul className="divide-y divide-gray-800 rounded-md border border-gray-800">
        {data.files.map((file) => (
          <li key={file.name} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
            <span className="text-gray-300">
              {formatDateTime(file.created_at, timeFormat)} · {formatBytes(file.size)}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" asChild>
                <a href={scheduledFileUrl(file.name)} download={file.name} aria-label="Download backup file">
                  <Download className="h-4 w-4" />
                </a>
              </Button>
              <Button variant="outline" size="sm" onClick={() => setToStage(file.name)} aria-label="Restore from this file">
                <RotateCcw className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="sm" onClick={() => setToDelete(file.name)} aria-label="Delete backup file">
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {data.other_backups > 0 && (
        <p className="text-xs text-gray-400">
          {data.other_backups} other DockMon backup file(s) in this folder belong to another install or were downloaded
          manually; DockMon leaves them alone.
        </p>
      )}

      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete backup file?</AlertDialogTitle>
            <AlertDialogDescription>This removes the file from the backup folder. It cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete) deleteFile.mutate(toDelete)
                setToDelete(null)
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={toStage !== null}
        onOpenChange={(open) => {
          if (!open) {
            setToStage(null)
            setStagePassphrase('')
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Restore DockMon from this backup?</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2">
                <p>
                  The backup is validated and staged; it is applied when DockMon restarts. The database and the
                  compose/.env files of the stacks in the backup are replaced; other stacks and all container data are
                  left as they are.
                </p>
                <label htmlFor="stage-file-passphrase" className="block text-sm font-medium text-gray-300">
                  Passphrase of this backup
                </label>
                <input
                  id="stage-file-passphrase"
                  type="password"
                  autoComplete="off"
                  value={stagePassphrase}
                  onChange={(e) => setStagePassphrase(e.target.value)}
                  className={INPUT_CLASS}
                />
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={stagePassphrase.length === 0}
              onClick={() => {
                if (toStage) stageFile.mutate({ name: toStage, passphrase: stagePassphrase, replace: false })
                setToStage(null)
                setStagePassphrase('')
              }}
            >
              Stage restore
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export function ScheduledBackupsSection() {
  const { data: saved, refetch } = useBackupSchedule()
  const run = useRunScheduledBackup()
  const { timeFormat } = useTimeFormat()

  if (!saved) return null

  return (
    <div>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-white">Scheduled Backups</h3>
          <p className="mt-1 text-xs text-gray-400">
            Written to {saved.destination.path}
            {saved.destination.free_bytes !== null && ` (${formatBytes(saved.destination.free_bytes)} free)`}. Failures raise the &quot;Alert System Health&quot; alert, which only
            notifies you once that rule has a notification channel.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void refetch()} aria-label="Refresh scheduled backups">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>
      <div className="space-y-4">
        <DestinationWarnings destination={saved.destination} />
        <div className="text-xs text-gray-400">
          {saved.last_run_at ? (
            <p>
              Last run {formatDateTime(saved.last_run_at, timeFormat)}:{' '}
              <span className={saved.last_status === 'failed' ? 'text-red-400' : 'text-gray-300'}>
                {saved.last_status ?? 'unknown'}
              </span>
            </p>
          ) : (
            <p>No scheduled backup has run yet.</p>
          )}
          {saved.last_file && <p>Last file: {saved.last_file}</p>}
          {saved.last_error && <p className="text-red-400">{saved.last_error}</p>}
          {saved.next_run_at && <p>Next run {formatDateTime(saved.next_run_at, timeFormat)}.</p>}
        </div>
        <ScheduleForm key={`${saved.enabled}-${saved.schedule}-${saved.retention}-${saved.include_stats}`} saved={saved} />
        <Button variant="outline" onClick={() => run.mutate()} disabled={run.isPending || !saved.passphrase_set}>
          <Play className="mr-2 h-4 w-4" />
          {run.isPending ? 'Running…' : 'Run now'}
        </Button>
        <ScheduledFiles />
      </div>
    </div>
  )
}
