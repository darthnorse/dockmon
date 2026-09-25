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
