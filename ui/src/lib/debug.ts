/**
 * Debug Utilities
 *
 * Centralized logging that can be enabled/disabled via environment variable
 * or localStorage flag for production debugging.
 *
 * Usage:
 *   debug.log('WebSocket', 'Connected to server')
 *   debug.warn('API', 'Retrying request...')
 *   debug.error('Auth', 'Login failed', error)
 */

const DEBUG_KEY = 'dockmon:debug'

/**
 * Check if debugging is enabled
 * - Always enabled in development
 * - In production, enabled via localStorage flag
 */
function isDebugEnabled(): boolean {
  // Always enable in development
  if (process.env.NODE_ENV === 'development') {
    return true
  }

  // In production, check localStorage flag
  if (typeof window !== 'undefined') {
    try {
      return localStorage.getItem(DEBUG_KEY) === 'true'
    } catch (e) {
      // localStorage may throw in incognito/private mode or if quota exceeded
      console.warn('Failed to access localStorage for debug flag:', e)
      return false
    }
  }

  return false
}

/**
 * Enable debug mode in production
 * Run in browser console: window.enableDebug()
 */
if (typeof window !== 'undefined') {
  ;(window as any).enableDebug = () => {
    try {
      localStorage.setItem(DEBUG_KEY, 'true')
      console.log('✅ Debug mode enabled. Reload to see debug messages.')
    } catch (e) {
      console.error('Failed to enable debug mode (localStorage unavailable):', e)
    }
  }
  ;(window as any).disableDebug = () => {
    try {
      localStorage.removeItem(DEBUG_KEY)
      console.log('❌ Debug mode disabled.')
    } catch (e) {
      console.error('Failed to disable debug mode (localStorage unavailable):', e)
    }
  }
}

/**
 * Debug logger with namespace support
 */
export const debug = {
  /**
   * Log informational message
   */
  log(namespace: string, ...args: unknown[]): void {
    if (isDebugEnabled()) {
      console.log(`[${namespace}]`, ...args)
    }
  },

  /**
   * Log warning message
   */
  warn(namespace: string, ...args: unknown[]): void {
    if (isDebugEnabled()) {
      console.warn(`[${namespace}]`, ...args)
    }
  },

  /**
   * Log error message (always shown, even in production)
   */
  error(namespace: string, ...args: unknown[]): void {
    console.error(`[${namespace}]`, ...args)
  },

  /**
   * Check if debug is enabled
   */
  isEnabled(): boolean {
    return isDebugEnabled()
  },
}
