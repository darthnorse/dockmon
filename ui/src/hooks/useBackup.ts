import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, apiClient } from '@/lib/api/client'
import { getBasePath } from '@/lib/utils/basePath'
import { getErrorMessage } from '@/lib/utils/errors'
import type {
  BackupDownload,
  BackupManifestSummary,
  BackupSchedule,
  BackupScheduleUpdate,
  BackupStatus,
  ScheduledBackupFiles,
  ScheduledRunResult,
  StageBackupRequest,
} from '@/types/backup'

const BACKUP_STATUS_KEY = ['backup-status']
const BACKUP_SCHEDULE_KEY = ['backup-schedule']
const SCHEDULED_FILES_KEY = ['backup-scheduled-files']
// Server-side destination status is cached, so this stays cheap even on a slow share
const SCHEDULE_REFETCH_MS = 60_000

export function isAllHostsRequired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403
}

export function useBackupStatus() {
  return useQuery({
    queryKey: BACKUP_STATUS_KEY,
    queryFn: () => apiClient.get<BackupStatus>('/v2/backup/status'),
    retry: (failureCount, error) => !isAllHostsRequired(error) && failureCount < 2,
    refetchInterval: (query) => (query.state.data?.busy ? 3000 : false),
  })
}

export function backupDownloadUrl(downloadId: string): string {
  return `${getBasePath()}/api/v2/backup/downloads/${downloadId}`
}

// A plain navigation lets the browser stream a multi-gigabyte file to disk instead of holding it in memory
function startDownload(download: BackupDownload): void {
  const link = document.createElement('a')
  link.href = backupDownloadUrl(download.download_id)
  link.download = download.filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

export function useCreateBackup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { passphrase: string; include_stats: boolean }) =>
      apiClient.post<BackupDownload>('/v2/backup', body),
    onSuccess: (download) => {
      startDownload(download)
      toast.success(`Backup ready: ${download.filename}`)
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY }),
    onError: (error) => toast.error(`Backup failed: ${getErrorMessage(error, 'Unexpected error')}`),
  })
}

export function useStageBackup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ file, passphrase, replace }: StageBackupRequest) => {
      const upload = await apiClient.postBinary<{ upload_id: string; size: number }>('/v2/backup/uploads', file)
      return apiClient.post<BackupManifestSummary>('/v2/backup/restore', {
        upload_id: upload.upload_id,
        passphrase,
        replace,
      })
    },
    onSuccess: () => {
      toast.success('Backup validated and staged')
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY }),
    onError: (error) => toast.error(`Restore not staged: ${getErrorMessage(error, 'Unexpected error')}`),
  })
}

export function useCancelStagedRestore() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => apiClient.delete<{ cancelled: boolean }>('/v2/backup/restore/pending'),
    onSuccess: () => {
      toast.success('Staged restore cancelled')
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY }),
    onError: (error) => toast.error(`Could not cancel: ${getErrorMessage(error, 'Unexpected error')}`),
  })
}

export function useStageRollback() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (rollbackId: string) =>
      apiClient.post<BackupManifestSummary>(`/v2/backup/rollbacks/${encodeURIComponent(rollbackId)}/stage`, {
        replace: false,
      }),
    onSuccess: () => {
      toast.success('Rollback copy staged')
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY }),
    onError: (error) => toast.error(`Could not stage rollback: ${getErrorMessage(error, 'Unexpected error')}`),
  })
}

export function useDeleteRollback() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (rollbackId: string) =>
      apiClient.delete<Record<string, never>>(`/v2/backup/rollbacks/${encodeURIComponent(rollbackId)}`),
    onSuccess: () => {
      toast.success('Rollback copy deleted')
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY }),
    onError: (error) => toast.error(`Could not delete rollback copy: ${getErrorMessage(error, 'Unexpected error')}`),
  })
}

export function useBackupSchedule() {
  return useQuery({
    queryKey: BACKUP_SCHEDULE_KEY,
    queryFn: () => apiClient.get<BackupSchedule>('/v2/backup/settings'),
    refetchInterval: SCHEDULE_REFETCH_MS,
  })
}

export function useScheduledFiles() {
  return useQuery({
    queryKey: SCHEDULED_FILES_KEY,
    queryFn: () => apiClient.get<ScheduledBackupFiles>('/v2/backup/files'),
    refetchInterval: SCHEDULE_REFETCH_MS,
  })
}

export function scheduledFileUrl(name: string): string {
  return `${getBasePath()}/api/v2/backup/files/${encodeURIComponent(name)}`
}

function useInvalidateSchedule() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: BACKUP_SCHEDULE_KEY })
    void queryClient.invalidateQueries({ queryKey: SCHEDULED_FILES_KEY })
    void queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY })
  }
}

export function useUpdateBackupSchedule() {
  const invalidate = useInvalidateSchedule()
  return useMutation({
    mutationFn: (update: BackupScheduleUpdate) => apiClient.put<BackupSchedule>('/v2/backup/settings', update),
    onSuccess: () => toast.success('Backup schedule saved'),
    onSettled: invalidate,
    onError: (error) => toast.error(`Schedule not saved: ${getErrorMessage(error, 'Unexpected error')}`),
  })
}

export function useRunScheduledBackup() {
  const invalidate = useInvalidateSchedule()
  return useMutation({
    mutationFn: () => apiClient.post<ScheduledRunResult>('/v2/backup/run'),
    onSuccess: (result) => {
      if (result.status === 'failed') {
        toast.error(`Backup failed: ${result.error ?? 'see the DockMon log'}`)
      } else {
        toast.success(`Backup written: ${result.file ?? ''}`)
      }
    },
    onSettled: invalidate,
    onError: (error) => toast.error(`Backup not started: ${getErrorMessage(error, 'Unexpected error')}`),
  })
}

export function useDeleteScheduledFile() {
  const invalidate = useInvalidateSchedule()
  return useMutation({
    mutationFn: (name: string) =>
      apiClient.delete<Record<string, never>>(`/v2/backup/files/${encodeURIComponent(name)}`),
    onSuccess: () => toast.success('Backup file deleted'),
    onSettled: invalidate,
    onError: (error) => toast.error(`Could not delete: ${getErrorMessage(error, 'Unexpected error')}`),
  })
}

export function useStageScheduledFile() {
  const invalidate = useInvalidateSchedule()
  return useMutation({
    mutationFn: ({ name, passphrase, replace }: { name: string; passphrase: string; replace: boolean }) =>
      apiClient.post<BackupManifestSummary>(`/v2/backup/files/${encodeURIComponent(name)}/stage`, {
        passphrase,
        replace,
      }),
    onSuccess: () => toast.success('Backup validated and staged'),
    onSettled: invalidate,
    onError: (error) => toast.error(`Restore not staged: ${getErrorMessage(error, 'Unexpected error')}`),
  })
}
