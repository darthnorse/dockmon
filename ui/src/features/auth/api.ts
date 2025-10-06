/**
 * Authentication API
 *
 * SECURITY: Uses v2 cookie-based authentication
 * - HttpOnly cookies (XSS protection)
 * - SameSite=strict (CSRF protection)
 * - Secure flag (HTTPS only)
 */

import { apiClient } from '@/lib/api/client'
import type { LoginRequest, LoginResponse, CurrentUserResponse } from '@/types/api'

export const authApi = {
  /**
   * Login with username/password
   * Cookie is set automatically by backend (HttpOnly, Secure, SameSite=strict)
   */
  login: async (credentials: LoginRequest): Promise<LoginResponse> => {
    return apiClient.post<LoginResponse>('/v2/auth/login', credentials)
  },

  /**
   * Logout and clear session cookie
   */
  logout: async (): Promise<void> => {
    await apiClient.post<void>('/v2/auth/logout')
  },

  /**
   * Get current authenticated user
   * Returns 401 if not authenticated
   */
  getCurrentUser: async (): Promise<CurrentUserResponse> => {
    return apiClient.get<CurrentUserResponse>('/v2/auth/me')
  },
}
