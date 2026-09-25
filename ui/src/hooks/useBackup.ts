import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, apiClient } from '@/lib/api/client'
import { getBasePath } from '@/lib/utils/basePath'
import type { BackupDownload, BackupManifestSummary, BackupStatus, StageBackupRequest } from '@/types/backup'

const BACKUP_STATUS_KEY = ['backup-status']

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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unexpected error'
}

export function useCreateBackup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { passphrase: string; include_stats: boolean }) =>
      apiClient.post<BackupDownload>('/v2/backup', body),
    onSuccess: (download) => {
      startDownload(download)
      toast.success(`Backup ready: ${download.filename}`)
      void queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY })
    },
    onError: (error) => toast.error(`Backup failed: ${errorMessage(error)}`),
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
      void queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY })
    },
    onError: (error) => toast.error(`Restore not staged: ${errorMessage(error)}`),
  })
}

export function useCancelStagedRestore() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => apiClient.delete<{ cancelled: boolean }>('/v2/backup/restore/pending'),
    onSuccess: () => {
      toast.success('Staged restore cancelled')
      void queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY })
    },
    onError: (error) => toast.error(`Could not cancel: ${errorMessage(error)}`),
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
      void queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY })
    },
    onError: (error) => toast.error(`Could not stage rollback: ${errorMessage(error)}`),
  })
}

export function useDeleteRollback() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (rollbackId: string) =>
      apiClient.delete<Record<string, never>>(`/v2/backup/rollbacks/${encodeURIComponent(rollbackId)}`),
    onSuccess: () => {
      toast.success('Rollback copy deleted')
      void queryClient.invalidateQueries({ queryKey: BACKUP_STATUS_KEY })
    },
    onError: (error) => toast.error(`Could not delete rollback copy: ${errorMessage(error)}`),
  })
}
