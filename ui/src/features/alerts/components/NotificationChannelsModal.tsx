/**
 * NotificationChannelsModal Component
 *
 * Modal for managing notification channels
 */

import { useState } from 'react'
import { X, Plus, Trash2, Edit, Power, PowerOff, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react'
import { Smartphone, Send, MessageSquare, Hash, Bell, Mail, Users, BellRing } from 'lucide-react'
import {
  useNotificationChannels,
  useCreateChannel,
  useUpdateChannel,
  useDeleteChannel,
  useTestChannel,
  useDependentAlerts,
  NotificationChannel,
  ChannelCreateRequest,
} from '../hooks/useNotificationChannels'
import { ChannelForm } from './ChannelForm'

interface Props {
  onClose: () => void
}

type View = 'list' | 'create' | 'edit'

const CHANNEL_ICONS: Record<string, any> = {
  telegram: Send,
  discord: MessageSquare,
  slack: Hash,
  teams: Users,
  pushover: Smartphone,
  gotify: Bell,
  ntfy: BellRing,
  smtp: Mail,
}

export function NotificationChannelsModal({ onClose }: Props) {
  const [view, setView] = useState<View>('list')
  const [selectedChannel, setSelectedChannel] = useState<NotificationChannel | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const { data: channelsData, isLoading } = useNotificationChannels()
  const createChannel = useCreateChannel()
  const updateChannel = useUpdateChannel()
  const deleteChannel = useDeleteChannel()
  const testChannel = useTestChannel()
  const { data: dependentData } = useDependentAlerts(deleteConfirm)

  const channels = channelsData?.channels || []

  const handleCreate = async (data: ChannelCreateRequest) => {
    try {
      await createChannel.mutateAsync(data)
      setView('list')
      setTestResult(null)
    } catch (error: any) {
      console.error('Failed to create channel:', error)
    }
  }

  const handleUpdate = async (data: ChannelCreateRequest) => {
    if (!selectedChannel) return
    try {
      await updateChannel.mutateAsync({
        channelId: selectedChannel.id,
        updates: data,
      })
      setView('list')
      setSelectedChannel(null)
      setTestResult(null)
    } catch (error: any) {
      console.error('Failed to update channel:', error)
    }
  }

  const handleDelete = async (channelId: number) => {
    try {
      await deleteChannel.mutateAsync(channelId)
      setDeleteConfirm(null)
    } catch (error: any) {
      console.error('Failed to delete channel:', error)
    }
  }

  const handleToggleEnabled = async (channel: NotificationChannel) => {
    try {
      await updateChannel.mutateAsync({
        channelId: channel.id,
        updates: { enabled: !channel.enabled },
      })
    } catch (error: any) {
      console.error('Failed to toggle channel:', error)
    }
  }

  const handleTest = async (_data: ChannelCreateRequest) => {
    // For new channels, we can't test until created
    // For existing channels, test using the channel ID
    if (selectedChannel) {
      try {
        const result = await testChannel.mutateAsync(selectedChannel.id)
        if (result.success) {
          setTestResult({ success: true, message: 'Test notification sent successfully!' })
        } else {
          setTestResult({ success: false, message: result.error || 'Test failed' })
        }
      } catch (error: any) {
        setTestResult({ success: false, message: error.message || 'Test failed' })
      }
    } else {
      setTestResult({ success: false, message: 'Please save the channel first before testing' })
    }
  }

  const handleEdit = (channel: NotificationChannel) => {
    setSelectedChannel(channel)
    setView('edit')
    setTestResult(null)
  }

  const handleCancelForm = () => {
    setView('list')
    setSelectedChannel(null)
    setTestResult(null)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-4xl rounded-lg border border-gray-700 bg-[#0d1117] shadow-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-700 px-6 py-4 sticky top-0 bg-[#0d1117] z-10">
          <h2 className="text-xl font-semibold text-white">
            {view === 'list' ? 'Notification Channels' : view === 'create' ? 'Add Notification Channel' : 'Edit Notification Channel'}
          </h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          {view === 'list' && (
            <>
              {/* Add Channel Button */}
              <div className="mb-6">
                <button
                  onClick={() => setView('create')}
                  className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
                >
                  <Plus className="h-4 w-4" />
                  Add Channel
                </button>
              </div>

              {/* Channels List */}
              {isLoading ? (
                <div className="text-center py-12 text-gray-400">Loading channels...</div>
              ) : channels.length === 0 ? (
                <div className="text-center py-12">
                  <Bell className="h-12 w-12 text-gray-600 mx-auto mb-3" />
                  <p className="text-gray-400 mb-2">No notification channels configured</p>
                  <p className="text-sm text-gray-500">Add a channel to start receiving alert notifications</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {channels.map((channel) => {
                    const IconComponent = CHANNEL_ICONS[channel.type] || Bell
                    return (
                      <div
                        key={channel.id}
                        className="flex items-center justify-between rounded-lg border border-gray-700 bg-gray-800/30 p-4 hover:bg-gray-800/50 transition-colors"
                      >
                        <div className="flex items-center gap-4 flex-1 min-w-0">
                          <IconComponent className="h-5 w-5 text-gray-400 flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <h3 className="text-sm font-medium text-white truncate">{channel.name}</h3>
                              {channel.enabled ? (
                                <span className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2 py-0.5 text-xs text-green-400">
                                  <Power className="h-3 w-3" />
                                  Enabled
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 rounded-full bg-gray-500/10 px-2 py-0.5 text-xs text-gray-400">
                                  <PowerOff className="h-3 w-3" />
                                  Disabled
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-gray-400 mt-0.5 capitalize">{channel.type}</p>
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          <button
                            onClick={async () => {
                              try {
                                const result = await testChannel.mutateAsync(channel.id)
                                if (result.success) {
                                  alert('Test notification sent successfully!')
                                } else {
                                  alert(`Test failed: ${result.error || 'Unknown error'}`)
                                }
                              } catch (error: any) {
                                alert(`Test failed: ${error.message || 'Unknown error'}`)
                              }
                            }}
                            disabled={!channel.enabled}
                            className="rounded-md bg-gray-700 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            Test
                          </button>
                          <button
                            onClick={() => handleToggleEnabled(channel)}
                            className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white"
                            title={channel.enabled ? 'Disable channel' : 'Enable channel'}
                          >
                            {channel.enabled ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
                          </button>
                          <button
                            onClick={() => handleEdit(channel)}
                            className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white"
                            title="Edit channel"
                          >
                            <Edit className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => setDeleteConfirm(channel.id)}
                            className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-700 hover:text-red-400"
                            title="Delete channel"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </>
          )}

          {(view === 'create' || view === 'edit') && (
            <div>
              {testResult && (
                <div className={`mb-4 rounded-md p-3 flex items-start gap-2 ${testResult.success ? 'bg-green-500/10 border border-green-500/20' : 'bg-red-500/10 border border-red-500/20'}`}>
                  {testResult.success ? (
                    <CheckCircle2 className="h-5 w-5 text-green-400 flex-shrink-0 mt-0.5" />
                  ) : (
                    <XCircle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
                  )}
                  <p className={`text-sm ${testResult.success ? 'text-green-400' : 'text-red-400'}`}>
                    {testResult.message}
                  </p>
                </div>
              )}
              <ChannelForm
                channel={selectedChannel}
                onSubmit={view === 'create' ? handleCreate : handleUpdate}
                onCancel={handleCancelForm}
                onTest={handleTest}
                isSubmitting={createChannel.isPending || updateChannel.isPending}
                isTesting={testChannel.isPending}
              />
            </div>
          )}
        </div>
      </div>

      {/* Delete Confirmation Dialog */}
      {deleteConfirm !== null && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-md rounded-lg border border-gray-700 bg-[#0d1117] p-6">
            <div className="flex items-start gap-3 mb-4">
              <AlertTriangle className="h-6 w-6 text-yellow-500 flex-shrink-0" />
              <div>
                <h3 className="text-lg font-semibold text-white mb-1">Delete Notification Channel?</h3>
                <p className="text-sm text-gray-400">
                  This will permanently delete the channel and remove it from all alert rules.
                </p>
                {dependentData && dependentData.alert_count > 0 && (
                  <p className="text-sm text-yellow-400 mt-2">
                    Warning: {dependentData.alert_count} alert rule{dependentData.alert_count > 1 ? 's' : ''} will be updated.
                  </p>
                )}
              </div>
            </div>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="rounded-md bg-gray-800 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-700"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                disabled={deleteChannel.isPending}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
              >
                {deleteChannel.isPending ? 'Deleting...' : 'Delete Channel'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
