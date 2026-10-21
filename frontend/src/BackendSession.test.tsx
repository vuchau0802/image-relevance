import { beforeEach, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import BackendSession from './BackendSession'
import { apiFetch } from './http'

const { getToken } = vi.hoisted(() => ({
  getToken: vi.fn(),
}))

vi.mock('@clerk/react', () => ({
  useAuth: () => ({
    getToken,
    userId: 'user_test',
  }),
}))

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

function renderSession() {
  return render(
    <BackendSession>
      <p>Account content</p>
    </BackendSession>,
  )
}

beforeEach(() => {
  getToken.mockReset()
  mockedFetch.mockReset()
  getToken.mockResolvedValue('synthetic-session-token')
})

test('shows content only after backend verification', async () => {
  mockedFetch
    .mockResolvedValueOnce(response({ user_id: 'user_test' }))
    .mockResolvedValueOnce(response({ workspace_id: 'ws_test' }))

  renderSession()

  expect(screen.queryByText('Account content')).not.toBeInTheDocument()

  expect(
    await screen.findByText('Account connected.'),
  ).toBeInTheDocument()

  expect(screen.getByText('Account content')).toBeInTheDocument()
  expect(mockedFetch).toHaveBeenCalledWith(
    '/me',
    expect.any(AbortSignal),
    'synthetic-session-token',
  )
  expect(mockedFetch).toHaveBeenCalledWith(
    '/workspace',
    expect.any(AbortSignal),
    'synthetic-session-token',
    { method: 'POST' },
  )
})

test('missing session token blocks content without an API request', async () => {
  getToken.mockResolvedValueOnce(null)

  renderSession()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Please sign out and sign in again.',
  )
  expect(screen.queryByText('Account content')).not.toBeInTheDocument()
  mockedFetch.mock.calls.forEach(() => {
    throw new Error('API should not be called without a token')
  })
  expect(mockedFetch).not.toHaveBeenCalled()
})

test('rejected authentication blocks content', async () => {
  mockedFetch.mockResolvedValueOnce(response({}, 401))

  renderSession()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Your session could not be verified. Please sign in again.',
  )
  expect(screen.queryByText('Account content')).not.toBeInTheDocument()
})

test('a different backend identity blocks content', async () => {
  mockedFetch.mockResolvedValueOnce(
    response({ user_id: 'user_other' }),
  )

  renderSession()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Account verification failed. Please sign in again.',
  )
  expect(screen.queryByText('Account content')).not.toBeInTheDocument()
})

test('retry recovers after a backend outage', async () => {
  const user = userEvent.setup()

  mockedFetch
    .mockResolvedValueOnce(response({}, 503))
    .mockResolvedValueOnce(response({ user_id: 'user_test' }))
    .mockResolvedValueOnce(response({ workspace_id: 'ws_test' }))

  renderSession()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Unable to connect your account. Please try again.',
  )

  await user.click(
    screen.getByRole('button', { name: 'Retry connection' }),
  )

  expect(
    await screen.findByText('Account connected.'),
  ).toBeInTheDocument()

  expect(screen.getByText('Account content')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(mockedFetch).toHaveBeenCalledTimes(3)
})

test('workspace initialization failure blocks content', async () => {
  mockedFetch
    .mockResolvedValueOnce(response({ user_id: 'user_test' }))
    .mockResolvedValueOnce(response({}, 503))

  renderSession()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Unable to prepare your workspace. Please try again.',
  )

  expect(screen.queryByText('Account content')).not.toBeInTheDocument()
})
