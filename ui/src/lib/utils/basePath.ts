/**
 * Returns the application base path with trailing slash stripped.
 * Centralizes the Vite BASE_URL normalization used for API URLs and WebSocket paths.
 */
export function getBasePath(): string {
  return import.meta.env.BASE_URL.replace(/\/$/, '')
}
