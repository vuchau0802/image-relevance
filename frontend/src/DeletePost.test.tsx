import { beforeEach, expect, test, vi } from 'vitest'
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { deletePost, getPost } from './api'
import type { CreatedPost } from './api'
import DeletePost from './DeletePost'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getPost: vi.fn(),
  deletePost: vi.fn(),
}))

const mockedGet = vi.mocked(getPost)
const mockedDelete = vi.mocked(deletePost)

const post: CreatedPost = {
  id: 'post_test',
  title: 'Selected forest article',
  content: 'An article about a forest.',
  required_subject: 'forest',
}

beforeEach(() => {
  mockedGet.mockReset()
  mockedDelete.mockReset()
  getSessionToken.mockReset()
  getSessionToken.mockResolvedValue('synthetic-token')
  mockedGet.mockResolvedValue(post)
  mockedDelete.mockResolvedValue(undefined)
})

async function openConfirmation() {
  const user = userEvent.setup()
  await user.click(
    screen.getByRole('button', { name: 'Delete selected post' }),
  )
  await screen.findByText(post.title)
  return user
}

test('does not request anything before opening confirmation', () => {
  render(<DeletePost postId={post.id} onDeleted={vi.fn()} />)

  expect(mockedGet).not.toHaveBeenCalled()
  expect(mockedDelete).not.toHaveBeenCalled()
})

test('identifies the selected post without deleting it', async () => {
  render(<DeletePost postId={post.id} onDeleted={vi.fn()} />)
  await openConfirmation()

  expect(
    screen.getByRole('region', { name: 'Confirm post deletion' }),
  ).toHaveTextContent('Required subject: forest')
  expect(mockedGet).toHaveBeenCalledWith(
    post.id,
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(mockedDelete).not.toHaveBeenCalled()
})

test('cancelling confirmation sends no deletion request', async () => {
  const onDeleted = vi.fn()
  render(<DeletePost postId={post.id} onDeleted={onDeleted} />)
  const user = await openConfirmation()

  await user.click(
    screen.getByRole('button', { name: 'Cancel deletion' }),
  )

  expect(
    screen.getByRole('button', { name: 'Delete selected post' }),
  ).toBeInTheDocument()
  expect(mockedDelete).not.toHaveBeenCalled()
  expect(onDeleted).not.toHaveBeenCalled()
})

test('deletes only after confirmation and reports the post ID', async () => {
  const onDeleted = vi.fn()
  render(<DeletePost postId={post.id} onDeleted={onDeleted} />)
  const user = await openConfirmation()

  await user.click(
    screen.getByRole('button', { name: 'Confirm deletion' }),
  )

  await waitFor(() => {
    expect(onDeleted).toHaveBeenCalledExactlyOnceWith(post.id)
  })
  expect(mockedDelete).toHaveBeenCalledWith(
    post.id,
    expect.any(AbortSignal),
    'synthetic-token',
  )
})

test('failed deletion keeps confirmation open and allows retry', async () => {
  mockedDelete.mockRejectedValueOnce(
    new Error('Post preparation is queued or processing.'),
  )
  const onDeleted = vi.fn()
  render(<DeletePost postId={post.id} onDeleted={onDeleted} />)
  const user = await openConfirmation()

  await user.click(
    screen.getByRole('button', { name: 'Confirm deletion' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Post preparation is queued or processing.',
  )
  expect(screen.getByText(post.title)).toBeInTheDocument()
  expect(onDeleted).not.toHaveBeenCalled()

  await user.click(
    screen.getByRole('button', { name: 'Confirm deletion' }),
  )

  await waitFor(() => {
    expect(onDeleted).toHaveBeenCalledExactlyOnceWith(post.id)
  })
  expect(mockedDelete).toHaveBeenCalledTimes(2)
})

test('failed detail loading prevents deletion until retry succeeds', async () => {
  const user = userEvent.setup()
  mockedGet.mockRejectedValueOnce(new Error('Details unavailable'))

  render(<DeletePost postId={post.id} onDeleted={vi.fn()} />)

  await user.click(
    screen.getByRole('button', { name: 'Delete selected post' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Details unavailable',
  )
  expect(
    screen.getByRole('button', { name: 'Confirm deletion' }),
  ).toBeDisabled()

  await user.click(
    screen.getByRole('button', {
      name: 'Try loading post details again',
    }),
  )

  await screen.findByText(post.title)
  expect(
    screen.getByRole('button', { name: 'Confirm deletion' }),
  ).toBeEnabled()
  expect(mockedDelete).not.toHaveBeenCalled()
})

test('blocks duplicate requests and ignores completion after unmount', async () => {
  let finish!: () => void
  mockedDelete.mockReturnValue(
    new Promise<void>((resolve) => {
      finish = resolve
    }),
  )
  const onDeleted = vi.fn()
  const view = render(
    <DeletePost postId={post.id} onDeleted={onDeleted} />,
  )
  await openConfirmation()

  await act(async () => {
    const button = screen.getByRole('button', {
      name: 'Confirm deletion',
    })
    fireEvent.click(button)
    fireEvent.click(button)
  })

  expect(mockedDelete).toHaveBeenCalledOnce()
  expect(
    screen.getByRole('button', { name: 'Deleting…' }),
  ).toBeDisabled()

  const signal = mockedDelete.mock.calls[0][1]
  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish()
  })

  expect(onDeleted).not.toHaveBeenCalled()
})

test('cancelling detail loading ignores a late response', async () => {
  const user = userEvent.setup()
  let finish!: (value: CreatedPost) => void
  mockedGet.mockReturnValue(
    new Promise<CreatedPost>((resolve) => {
      finish = resolve
    }),
  )

  render(<DeletePost postId={post.id} onDeleted={vi.fn()} />)

  await user.click(
    screen.getByRole('button', { name: 'Delete selected post' }),
  )
  await waitFor(() => {
    expect(mockedGet).toHaveBeenCalledOnce()
  })
  const signal = mockedGet.mock.calls[0][1]

  await user.click(
    screen.getByRole('button', { name: 'Cancel deletion' }),
  )

  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish(post)
  })

  expect(
    screen.queryByRole('region', { name: 'Confirm post deletion' }),
  ).not.toBeInTheDocument()
  expect(mockedDelete).not.toHaveBeenCalled()
})