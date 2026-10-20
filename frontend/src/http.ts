const API_BASE = '/api'

// Temporary demo identity. Replace when authentication is implemented.
const DEMO_TENANT_ID = 'demo'

export function apiFetch(
  path: string,
  signal: AbortSignal,
): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    headers: { 'X-Tenant-ID': DEMO_TENANT_ID },
    signal,
  })
}