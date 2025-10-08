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
    return localStorage.getItem(DEBUG_KEY) === 'true'
  }

  return false
}

/**
 * Enable debug mode in production
 * Run in browser console: window.enableDebug()
 */
if (typeof window !== 'undefined') {
  ;(window as any).enableDebug = () => {
    localStorage.setItem(DEBUG_KEY, 'true')
    console.log('✅ Debug mode enabled. Reload to see debug messages.')
  }
  ;(window as any).disableDebug = () => {
    localStorage.removeItem(DEBUG_KEY)
    console.log('❌ Debug mode disabled.')
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
