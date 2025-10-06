/**
 * API Client Tests
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { apiClient, ApiError } from './client'

describe('ApiClient', () => {
  beforeEach(() => {
    // Mock fetch
    global.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('GET requests', () => {
    it('should make GET request with correct headers', async () => {
      const mockResponse = { data: 'test' }
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      const result = await apiClient.get('/test')

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/test',
        expect.objectContaining({
          method: 'GET',
          credentials: 'include',
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      )
      expect(result).toEqual(mockResponse)
    })

    it('should include query parameters', async () => {
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      await apiClient.get('/test', { params: { foo: 'bar', baz: 123 } })

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/test?foo=bar&baz=123',
        expect.any(Object)
      )
    })

    it('should handle 204 No Content', async () => {
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        status: 204,
        headers: new Headers({ 'content-length': '0' }),
      })

      const result = await apiClient.get('/test')

      expect(result).toEqual({})
    })
  })

  describe('POST requests', () => {
    it('should make POST request with JSON body', async () => {
      const requestData = { username: 'test', password: 'pass' }
      const mockResponse = { success: true }
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      const result = await apiClient.post('/auth/login', requestData)

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/auth/login',
        expect.objectContaining({
          method: 'POST',
          credentials: 'include',
          body: JSON.stringify(requestData),
        })
      )
      expect(result).toEqual(mockResponse)
    })

    it('should handle POST without body', async () => {
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      await apiClient.post('/auth/logout')

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/auth/logout',
        expect.objectContaining({
          method: 'POST',
          body: undefined,
        })
      )
    })
  })

  describe('PATCH requests', () => {
    it('should make PATCH request with JSON body', async () => {
      const requestData = { theme: 'dark' }
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      await apiClient.patch('/user/preferences', requestData)

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/user/preferences',
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify(requestData),
        })
      )
    })
  })

  describe('DELETE requests', () => {
    it('should make DELETE request', async () => {
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      await apiClient.delete('/user/preferences')

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/user/preferences',
        expect.objectContaining({
          method: 'DELETE',
        })
      )
    })
  })

  describe('Error handling', () => {
    it('should throw ApiError on 401 Unauthorized', async () => {
      const errorData = { detail: 'Invalid credentials' }
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        json: async () => errorData,
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      await expect(apiClient.get('/test')).rejects.toThrow(ApiError)
      await expect(apiClient.get('/test')).rejects.toMatchObject({
        status: 401,
        data: errorData,
      })
    })

    it('should throw ApiError on 429 Rate Limit', async () => {
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
        json: async () => ({ detail: 'Rate limit exceeded' }),
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      await expect(apiClient.post('/auth/login', {})).rejects.toMatchObject({
        status: 429,
      })
    })

    it('should handle non-JSON error responses', async () => {
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        text: async () => 'Server Error',
        headers: new Headers({ 'content-type': 'text/plain' }),
      })

      await expect(apiClient.get('/test')).rejects.toThrow(ApiError)
    })
  })

  describe('Security', () => {
    it('should always include credentials for cookies', async () => {
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      await apiClient.get('/test')

      expect(global.fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          credentials: 'include',
        })
      )
    })

    it('should set Content-Type to application/json', async () => {
      ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
        headers: new Headers({ 'content-type': 'application/json' }),
      })

      await apiClient.post('/test', {})

      expect(global.fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      )
    })
  })
})
