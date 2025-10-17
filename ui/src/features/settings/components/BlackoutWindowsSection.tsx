/**
 * BlackoutWindowsSection Component
 * Manage blackout windows for suppressing alerts during maintenance
 */

import { useState } from 'react'
import { useGlobalSettings, useUpdateGlobalSettings } from '@/hooks/useSettings'
import { Plus, Trash2, Edit, Power, PowerOff, Moon } from 'lucide-react'
import { toast } from 'sonner'

interface BlackoutWindow {
  name: string
  enabled: boolean
  start_time: string
  end_time: string
  days: number[]
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function BlackoutWindowsSection() {
  const { data: settings } = useGlobalSettings()
  const updateSettings = useUpdateGlobalSettings()

  const [view, setView] = useState<'list' | 'create' | 'edit'>('list')
  const [editIndex, setEditIndex] = useState<number | null>(null)
  const [formData, setFormData] = useState<BlackoutWindow>({
    name: '',
    enabled: true,
    start_time: '22:00',
    end_time: '06:00',
    days: [0, 1, 2, 3, 4], // Mon-Fri
  })

  const windows = settings?.blackout_windows || []

  const handleCreate = async () => {
    try {
      const newWindows = [...windows, formData]
      await updateSettings.mutateAsync({ blackout_windows: newWindows })
      setView('list')
      setFormData({
        name: '',
        enabled: true,
        start_time: '22:00',
        end_time: '06:00',
        days: [0, 1, 2, 3, 4],
      })
      toast.success('Blackout window created')
    } catch (error) {
      toast.error('Failed to create blackout window')
    }
  }

  const handleUpdate = async () => {
    if (editIndex === null) return
    try {
      const newWindows = [...windows]
      newWindows[editIndex] = formData
      await updateSettings.mutateAsync({ blackout_windows: newWindows })
      setView('list')
      setEditIndex(null)
      toast.success('Blackout window updated')
    } catch (error) {
      toast.error('Failed to update blackout window')
    }
  }

  const handleDelete = async (index: number) => {
    try {
      const newWindows = windows.filter((_, i) => i !== index)
      await updateSettings.mutateAsync({ blackout_windows: newWindows })
      toast.success('Blackout window deleted')
    } catch (error) {
      toast.error('Failed to delete blackout window')
    }
  }

  const handleToggleEnabled = async (index: number) => {
    try {
      const window = windows[index]
      if (!window) return
      const newWindows = [...windows]
      newWindows[index] = { ...window, enabled: !window.enabled }
      await updateSettings.mutateAsync({ blackout_windows: newWindows })
      toast.success(newWindows[index].enabled ? 'Window enabled' : 'Window disabled')
    } catch (error) {
      toast.error('Failed to toggle window')
    }
  }

  const handleEdit = (index: number) => {
    const window = windows[index]
    if (!window) return
    setFormData(window)
    setEditIndex(index)
    setView('edit')
  }

  const handleCancel = () => {
    setView('list')
    setEditIndex(null)
    setFormData({
      name: '',
      enabled: true,
      start_time: '22:00',
      end_time: '06:00',
      days: [0, 1, 2, 3, 4],
    })
  }

  const toggleDay = (day: number) => {
    setFormData(prev => ({
      ...prev,
      days: prev.days.includes(day)
        ? prev.days.filter(d => d !== day)
        : [...prev.days, day].sort()
    }))
  }

  if (view === 'create' || view === 'edit') {
    return (
      <div>
        <div className="mb-4">
          <button
            onClick={handleCancel}
            className="text-sm text-blue-400 hover:text-blue-300 underline"
          >
            ← Back to blackout windows
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Window Name *</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
              placeholder="e.g., Night Maintenance"
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Start Time *</label>
              <input
                type="time"
                value={formData.start_time}
                onChange={(e) => setFormData(prev => ({ ...prev, start_time: e.target.value }))}
                className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">End Time *</label>
              <input
                type="time"
                value={formData.end_time}
                onChange={(e) => setFormData(prev => ({ ...prev, end_time: e.target.value }))}
                className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">Active Days *</label>
            <div className="flex gap-2">
              {WEEKDAYS.map((day, index) => (
                <button
                  key={day}
                  onClick={() => toggleDay(index)}
                  className={`px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                    formData.days.includes(index)
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  {day}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="flex items-center gap-2 text-sm text-gray-300">
              <input
                type="checkbox"
                checked={formData.enabled}
                onChange={(e) => setFormData(prev => ({ ...prev, enabled: e.target.checked }))}
                className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0"
              />
              Enable this blackout window
            </label>
          </div>

          <div className="flex items-center gap-3 pt-4 border-t border-gray-700">
            <button
              onClick={handleCancel}
              className="rounded-md bg-gray-800 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-700"
            >
              Cancel
            </button>
            <button
              onClick={view === 'create' ? handleCreate : handleUpdate}
              disabled={!formData.name || formData.days.length === 0 || updateSettings.isPending}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {updateSettings.isPending ? 'Saving...' : view === 'create' ? 'Create Window' : 'Update Window'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">
          Suppress alert notifications during scheduled maintenance windows
        </p>
        <button
          onClick={() => setView('create')}
          className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          Add Window
        </button>
      </div>

      {windows.length === 0 ? (
        <div className="text-center py-8">
          <Moon className="h-12 w-12 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400 mb-2">No blackout windows configured</p>
          <p className="text-sm text-gray-500">Add a window to suppress alerts during maintenance</p>
        </div>
      ) : (
        <div className="space-y-3">
          {windows.map((window, index) => (
            <div
              key={window.name}
              className="flex items-center justify-between rounded-lg border border-gray-700 bg-gray-800/30 p-4 hover:bg-gray-800/50 transition-colors"
            >
              <div className="flex items-center gap-4 flex-1 min-w-0">
                <Moon className="h-5 w-5 text-gray-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-medium text-white truncate">{window.name}</h3>
                    {window.enabled ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2 py-0.5 text-xs text-green-400">
                        <Power className="h-3 w-3" />
                        Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-gray-500/10 px-2 py-0.5 text-xs text-gray-400">
                        <PowerOff className="h-3 w-3" />
                        Inactive
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {window.start_time} - {window.end_time} • {window.days.map(d => WEEKDAYS[d]).join(', ')}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleToggleEnabled(index)}
                  className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white"
                  title={window.enabled ? 'Disable window' : 'Enable window'}
                >
                  {window.enabled ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
                </button>
                <button
                  onClick={() => handleEdit(index)}
                  className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white"
                  title="Edit window"
                >
                  <Edit className="h-4 w-4" />
                </button>
                <button
                  onClick={() => handleDelete(index)}
                  className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-700 hover:text-red-400"
                  title="Delete window"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
