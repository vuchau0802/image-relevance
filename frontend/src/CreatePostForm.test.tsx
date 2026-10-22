import { beforeEach, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import CreatePostForm from './CreatePostForm'
import { createPost } from './api'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  createPost: vi.fn(),
}))

const mockedCreatePost = vi.mocked(createPost)

const payload = {
  title: 'Urban red foxes',
  content: 'A post about red foxes.',
  required_subject: 'red fox',
}

async function fillForm(
  user: ReturnType<typeof userEvent.setup>,
) {
  await user.type(
    screen.getByRole('textbox', { name: 'Title' }),
    payload.title,
  )
  await user.type(
    screen.getByRole('textbox', { name: 'Content' }),
    payload.content,
  )
  await user.type(
    screen.getByRole('textbox', { name: 'Required subject' }),
    payload.required_subject,
  )
}

beforeEach(() => {
  mockedCreatePost.mockReset()
  getSessionToken.mockReset()
  getSessionToken.mockResolvedValue('synthetic-session-token')
})

test('saves the post and clears the form after success', async () => {
  const user = userEvent.setup()
  const onCreated = vi.fn()

  mockedCreatePost.mockResolvedValue({
    id: 'post_new',
    ...payload,
  })

  render(<CreatePostForm onCreated={onCreated} />)
  await fillForm(user)

  await user.click(
    screen.getByRole('button', { name: 'Save post' }),
  )

  expect(
    await screen.findByText(
      'Post saved. Matching requires embedding preparation.',
    ),
  ).toBeInTheDocument()

  expect(mockedCreatePost).toHaveBeenCalledWith(
    payload,
    expect.any(AbortSignal),
    'synthetic-session-token',
  )
  expect(onCreated).toHaveBeenCalledOnce()
  expect(onCreated).toHaveBeenCalledWith('post_new')

  expect(screen.getByRole('textbox', { name: 'Title' })).toHaveValue('')
  expect(screen.getByRole('textbox', { name: 'Content' })).toHaveValue('')
  expect(
    screen.getByRole('textbox', { name: 'Required subject' }),
  ).toHaveValue('')
})

test('a failed save preserves entered content', async () => {
  const user = userEvent.setup()
  const onCreated = vi.fn()

  mockedCreatePost.mockRejectedValue(
    new Error('Could not save the post (503).'),
  )

  render(<CreatePostForm onCreated={onCreated} />)
  await fillForm(user)

  await user.click(
    screen.getByRole('button', { name: 'Save post' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not save the post (503).',
  )
  expect(screen.getByRole('textbox', { name: 'Title' })).toHaveValue(
    payload.title,
  )
  expect(screen.getByRole('textbox', { name: 'Content' })).toHaveValue(
    payload.content,
  )
  expect(
    screen.getByRole('textbox', { name: 'Required subject' }),
  ).toHaveValue(payload.required_subject)

  expect(onCreated).not.toHaveBeenCalled()
  expect(
    screen.getByRole('button', { name: 'Save post' }),
  ).toBeEnabled()
})

test('pending submission prevents duplicates and aborts on unmount', async () => {
  const user = userEvent.setup()
  const onCreated = vi.fn()

  mockedCreatePost.mockImplementation(() => new Promise(() => {}))

  const view = render(<CreatePostForm onCreated={onCreated} />)
  await fillForm(user)

  await user.dblClick(
    screen.getByRole('button', { name: 'Save post' }),
  )

  expect(mockedCreatePost).toHaveBeenCalledOnce()
  expect(
    screen.getByRole('button', { name: 'Saving…' }),
  ).toBeDisabled()

  const signal = mockedCreatePost.mock.calls[0][1]
  view.unmount()

  expect(signal.aborted).toBe(true)
  expect(onCreated).not.toHaveBeenCalled()
})

test('empty required fields prevent submission', async () => {
  const user = userEvent.setup()
  render(<CreatePostForm onCreated={vi.fn()} />)

  await user.click(
    screen.getByRole('button', { name: 'Save post' }),
  )

  expect(mockedCreatePost).not.toHaveBeenCalled()
  expect(getSessionToken).not.toHaveBeenCalled()
})