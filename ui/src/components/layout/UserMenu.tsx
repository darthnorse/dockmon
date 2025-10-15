/**
 * User Menu Dropdown
 *
 * Dropdown menu shown when clicking username in sidebar
 * Options: Account settings, Logout
 */

import { useState, useRef, useEffect } from 'react'
import { User, LogOut } from 'lucide-react'
import { useAuth } from '@/features/auth/AuthContext'
import { UserAccountModal } from '@/features/settings/UserAccountModal'
import { cn } from '@/lib/utils'

interface UserMenuProps {
  isCollapsed: boolean
}

export function UserMenu({ isCollapsed }: UserMenuProps) {
  const { user, logout } = useAuth()
  const [showMenu, setShowMenu] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowMenu(false)
      }
    }

    if (showMenu) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
    return undefined
  }, [showMenu])

  const handleLogout = async () => {
    setShowMenu(false)
    await logout()
  }

  const handleAccountSettings = () => {
    setShowMenu(false)
    setShowSettings(true)
  }

  return (
    <>
      <div ref={menuRef} className="relative">
        {/* User Info Button */}
        <button
          onClick={() => setShowMenu(!showMenu)}
          className={cn(
            'flex w-full items-start gap-3 rounded-lg p-2 transition-colors hover:bg-surface-2',
            isCollapsed && 'justify-center',
            showMenu && 'bg-surface-2'
          )}
          title="User Menu"
        >
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">
            {user?.username?.charAt(0).toUpperCase() || 'U'}
          </div>
          {!isCollapsed && (
            <div className="flex-1 overflow-hidden text-left">
              <p className="truncate text-sm font-medium">{user?.username || 'User'}</p>
              {user?.display_name && (
                <p className="truncate text-xs text-muted-foreground">{user.display_name}</p>
              )}
              <p className="truncate text-[10px] text-muted-foreground/70 mt-5">DockMon v2.0.0</p>
            </div>
          )}
        </button>

        {/* Dropdown Menu */}
        {showMenu && (
          <div
            className={cn(
              'absolute bottom-full mb-2 w-48 rounded-lg border border-border bg-surface-1 shadow-lg',
              isCollapsed ? 'left-0' : 'left-0 right-0'
            )}
          >
            <div className="p-1">
              {/* Account Settings */}
              <button
                onClick={handleAccountSettings}
                className="flex w-full items-center gap-3 rounded px-3 py-2 text-sm transition-colors hover:bg-surface-2"
              >
                <User className="h-4 w-4" />
                Account Settings
              </button>

              {/* Logout */}
              <button
                onClick={handleLogout}
                className="flex w-full items-center gap-3 rounded px-3 py-2 text-sm text-danger transition-colors hover:bg-danger/10"
              >
                <LogOut className="h-4 w-4" />
                Logout
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Account Settings Modal */}
      <UserAccountModal isOpen={showSettings} onClose={() => setShowSettings(false)} />
    </>
  )
}
