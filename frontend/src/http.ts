const API_BASE = '/api'

export function apiFetch(
  path: string,
  signal: AbortSignal,
  accessToken: string,
  options: RequestInit = {},
): Promise<Response> {
  if (typeof accessToken !== 'string' || !accessToken.trim()) {
    return Promise.reject(new Error('Please sign in again.'))
  }

  const headers = new Headers(options.headers)
  headers.set('Authorization', `Bearer ${accessToken}`)
  headers.delete('X-Tenant-ID')

  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    signal,
  })
}
