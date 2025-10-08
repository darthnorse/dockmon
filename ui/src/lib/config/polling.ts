/**
 * Polling Configuration
 *
 * Central configuration for data refresh intervals across the application.
 * Adjust these values to balance real-time updates vs server load.
 */

export const POLLING_CONFIG = {
  // Data refresh intervals (in milliseconds)
  CONTAINER_DATA: 5000,       // Container list and stats (5s) - frequent updates needed
  HOST_DATA: 10000,           // Host information (10s) - changes less frequently
  EVENTS: 3000,               // Real-time events (3s) - critical updates
  ALERTS: 5000,               // Alert status (5s) - important but not critical
  SETTINGS: 30000,            // Settings/config (30s) - rarely changes

  // WebSocket configuration
  WEBSOCKET_RECONNECT: 3000,  // Base reconnection delay (3s)
  WEBSOCKET_MAX_ATTEMPTS: 10, // Maximum reconnection attempts
  WEBSOCKET_MAX_DELAY: 30000, // Maximum delay cap (30s) for exponential backoff
} as const

/**
 * Development mode - more aggressive polling for better DX
 * Production mode - conservative polling to reduce server load
 */
export const getPollingInterval = (key: keyof typeof POLLING_CONFIG): number => {
  const interval = POLLING_CONFIG[key]

  // In development, you can optionally reduce intervals for faster feedback
  // Example: return Math.max(interval / 2, 1000) // Half the interval, minimum 1s

  return interval
}
