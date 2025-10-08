/**
 * API Client - Stable Boundary #1
 *
 * SECURITY:
 * - Uses cookie-based authentication (HttpOnly, Secure, SameSite=strict)
 * - Credentials always included for cookie transmission
 * - CSRF protection via SameSite=strict
 *
 * SWAPPABLE:
 * - Can swap to Orval-generated client later
 * - Can swap to gRPC without changing consuming code
 * - All API calls go through this single client
 */

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: unknown
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean>
}

class ApiClient {
  private baseURL: string

  constructor(baseURL = '/api') {
    this.baseURL = baseURL
  }

  /**
   * Core request method - all API calls go through here
   * SECURITY: Credentials 'include' ensures cookies are sent
   */
  private async request<T>(
    endpoint: string,
    options: RequestOptions = {}
  ): Promise<T> {
    const { params, ...fetchOptions } = options

    // Build URL with query params
    let url = `${this.baseURL}${endpoint}`
    if (params) {
      const searchParams = new URLSearchParams()
      Object.entries(params).forEach(([key, value]) => {
        searchParams.append(key, String(value))
      })
      url += `?${searchParams.toString()}`
    }

    const response = await fetch(url, {
      ...fetchOptions,
      credentials: 'include', // SECURITY: Include cookies (HttpOnly session)
      headers: {
        'Content-Type': 'application/json',
        ...fetchOptions.headers,
      },
    })

    // Handle error responses
    if (!response.ok) {
      const contentType = response.headers.get('content-type')
      let errorData: unknown

      if (contentType?.includes('application/json')) {
        errorData = await response.json() as unknown
      } else {
        errorData = await response.text()
      }

      throw new ApiError(
        `API Error: ${response.statusText}`,
        response.status,
        errorData
      )
    }

    // Handle empty responses (204 No Content, etc.)
    if (response.status === 204 || response.headers.get('content-length') === '0') {
      return {} as T
    }

    return response.json() as Promise<T>
  }

  // HTTP methods
  async get<T>(endpoint: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'GET' })
  }

  async post<T>(endpoint: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: 'POST',
      body: data !== undefined ? JSON.stringify(data) : null,
    })
  }

  async patch<T>(endpoint: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: 'PATCH',
      body: data !== undefined ? JSON.stringify(data) : null,
    })
  }

  async put<T>(endpoint: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: 'PUT',
      body: data !== undefined ? JSON.stringify(data) : null,
    })
  }

  async delete<T>(endpoint: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'DELETE' })
  }
}

// Export singleton instance
export const apiClient = new ApiClient()
