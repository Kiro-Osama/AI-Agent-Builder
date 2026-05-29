import { API_BASE, FETCH_TIMEOUT_MS } from './constants'

class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeoutMs = FETCH_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController()
  const id = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } finally {
    clearTimeout(id)
  }
}

export const api = {
  async get<T = unknown>(path: string, timeout?: number): Promise<T> {
    const res = await fetchWithTimeout(`${API_BASE}${path}`, {}, timeout)
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(body.detail || res.statusText, res.status)
    }
    return res.json()
  },

  async post<T = unknown>(path: string, data?: unknown, timeout?: number): Promise<T> {
    const res = await fetchWithTimeout(
      `${API_BASE}${path}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: data ? JSON.stringify(data) : undefined,
      },
      timeout,
    )
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(body.detail || res.statusText, res.status)
    }
    return res.json()
  },

  async put<T = unknown>(path: string, data?: unknown): Promise<T> {
    const res = await fetchWithTimeout(`${API_BASE}${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: data ? JSON.stringify(data) : undefined,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(body.detail || res.statusText, res.status)
    }
    return res.json()
  },

  async delete<T = unknown>(path: string): Promise<T> {
    const res = await fetchWithTimeout(`${API_BASE}${path}`, { method: 'DELETE' })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(body.detail || res.statusText, res.status)
    }
    return res.json()
  },

  async healthCheck(): Promise<boolean> {
    try {
      const res = await fetchWithTimeout('/health', {}, 5000)
      return res.ok
    } catch {
      return false
    }
  },
}
