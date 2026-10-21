import { beforeEach, expect, test, vi } from 'vitest'

import { getPosts } from './api'
import { apiFetch } from './http'

vi.mock('./http', () => ({
  apiFetch: vi.fn(),
}))

const mockedFetch = vi.mocked(apiFetch)

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  mockedFetch.mockReset()
})

test('combines posts from every page', async () => {
  const signal = new AbortController().signal

  const first = {
    id: 'custom_001',
    title: 'First post',
    required_subject: 'red fox',
  }
  const second = {
    id: 'custom_002',
    title: 'Second post',
    required_subject: 'pizza',
  }

  mockedFetch
    .mockResolvedValueOnce(response({
      items: [first],
      next_offset: 1,
    }))
    .mockResolvedValueOnce(response({
      items: [second],
      next_offset: null,
    }))

  await expect(getPosts(signal, 'synthetic-session-token')).resolves.toEqual([first, second])

  expect(mockedFetch).toHaveBeenCalledTimes(2)
  expect(mockedFetch).toHaveBeenNthCalledWith(
    1, '/posts?offset=0&limit=50', signal, 'synthetic-session-token',
  )
  expect(mockedFetch).toHaveBeenNthCalledWith(
    2, '/posts?offset=1&limit=50', signal, 'synthetic-session-token',
  )
})

test('returns an empty list without requesting another page', async () => {
  mockedFetch.mockResolvedValueOnce(response({
    items: [],
    next_offset: null,
  }))

  await expect(
    getPosts(new AbortController().signal, 'synthetic-session-token'),
  ).resolves.toEqual([])

  expect(mockedFetch).toHaveBeenCalledTimes(1)
})

test('rejects pagination that does not advance', async () => {
  mockedFetch.mockResolvedValueOnce(response({
    items: [],
    next_offset: 0,
  }))

  await expect(
    getPosts(new AbortController().signal, 'synthetic-session-token'),
  ).rejects.toThrow('Invalid post pagination response.')

  expect(mockedFetch).toHaveBeenCalledTimes(1)
})

test('fails if a later page cannot be loaded', async () => {
  mockedFetch
    .mockResolvedValueOnce(response({
      items: [{
        id: 'custom_001',
        title: 'First post',
        required_subject: 'red fox',
      }],
      next_offset: 1,
    }))
    .mockResolvedValueOnce(response({}, 502))

  await expect(
    getPosts(new AbortController().signal, 'synthetic-session-token'),
  ).rejects.toThrow('Could not load posts (502).')
})
