export interface BackupContentCounts {
  hosts: number
  users: number
  alert_rules: number
  stacks: string[]
}

export interface BackupManifestSummary {
  created_at: string
  app_version: string
  alembic_revision: string
  stats_history_included: boolean
  summary: BackupContentCounts
}

export interface BackupDownload {
  download_id: string
  filename: string
  size: number
  created_at: string
  expires_at: string
}

export interface RollbackCopy {
  id: string
  created_at: string | null
  replaced_by_backup_created_at: string | null
}

export interface LastRestore {
  restored_at: string | null
  backup: { created_at?: string; app_version?: string } | null
  initiated_by: string | null
}

export interface BackupStatus {
  busy: boolean
  pending: BackupManifestSummary | null
  rollbacks: RollbackCopy[]
  last_restore: LastRestore | null
  download: BackupDownload | null
}

export interface StageBackupRequest {
  file: File
  passphrase: string
  replace: boolean
}

export interface BackupDestination {
  path: string
  exists: boolean
  is_mountpoint: boolean
  writable: boolean
  same_filesystem_as_data: boolean
  free_bytes: number | null
}

export type ScheduledRunStatus = 'ok' | 'warning' | 'failed'

export interface BackupSchedule {
  enabled: boolean
  schedule: string
  retention: number
  include_stats: boolean
  passphrase_set: boolean
  last_run_at: string | null
  last_status: ScheduledRunStatus | null
  last_error: string | null
  last_file: string | null
  next_run_at: string | null
  timezone: string
  timezone_error: string | null
  destination: BackupDestination
}

export interface BackupScheduleUpdate {
  enabled?: boolean
  schedule?: string
  retention?: number
  include_stats?: boolean
  passphrase?: string
  clear_passphrase?: boolean
}

export interface ScheduledBackupFile {
  name: string
  size: number
  created_at: string
}

export interface ScheduledBackupFiles {
  files: ScheduledBackupFile[]
  other_backups: number
}

export interface ScheduledRunResult {
  status: ScheduledRunStatus
  file: string | null
  error: string | null
}
