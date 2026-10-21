import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { apiFetch } from './http'

const transport = vi.fn<typeof fetch>()

beforeEach(() => {
  transport.mockReset()
  transport.mockResolvedValue(new Response('{}', { status: 200 }))
  vi.stubGlobal('fetch', transport)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('sends a bearer token and preserves cancellation', async () => {
  const signal = new AbortController().signal

  await apiFetch('/posts', signal, 'synthetic-session-token')

  expect(transport).toHaveBeenCalledTimes(1)
  const [url, options] = transport.mock.calls[0]
  expect(url).toBe('/api/posts')
  expect(options?.signal).toBe(signal)
  const headers = new Headers(options?.headers)
  expect(headers.get('Authorization')).toBe('Bearer synthetic-session-token')
  expect(headers.has('X-Tenant-ID')).toBe(false)
})

test('removes caller tenant headers while preserving POST options', async () => {
  await apiFetch(
    '/workspace',
    new AbortController().signal,
    'synthetic-session-token',
    {
      method: 'POST',
      headers: {
        'X-Tenant-ID': 'another-workspace',
        Authorization: 'Bearer incorrect-token',
        'Content-Type': 'application/json',
      },
      body: '{}',
    },
  )

  const options = transport.mock.calls[0][1]
  const headers = new Headers(options?.headers)
  expect(options?.method).toBe('POST')
  expect(options?.body).toBe('{}')
  expect(headers.has('X-Tenant-ID')).toBe(false)
  expect(headers.get('Authorization')).toBe('Bearer synthetic-session-token')
  expect(headers.get('Content-Type')).toBe('application/json')
})

test.each(['', '   '])('missing token %j stops before fetch', async (token) => {
  await expect(
    apiFetch('/posts', new AbortController().signal, token),
  ).rejects.toThrow('Please sign in again.')

  expect(transport).not.toHaveBeenCalled()
})
