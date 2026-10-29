import { beforeEach, expect, test, vi } from 'vitest'
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { getPost, updatePost } from './api'
import type { CreatedPost } from './api'
import EditPostForm from './EditPostForm'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getPost: vi.fn(),
  updatePost: vi.fn(),
}))

const mockedGet = vi.mocked(getPost)
const mockedUpdate = vi.mocked(updatePost)

const original: CreatedPost = {
  id: 'post_test',
  title: 'Original title',
  content: 'Original article content.',
  required_subject: 'red fox',
}

beforeEach(() => {
  mockedGet.mockReset()
  mockedUpdate.mockReset()
  getSessionToken.mockReset()
  getSessionToken.mockResolvedValue('synthetic-token')
  mockedGet.mockResolvedValue(original)
})

test('loads and prefills the selected post', async () => {
  render(<EditPostForm postId="post_test" onSaved={vi.fn()} />)

  expect(
    await screen.findByRole('textbox', { name: 'Title' }),
  ).toHaveValue(original.title)
  expect(
    screen.getByRole('textbox', { name: 'Content' }),
  ).toHaveValue(original.content)
  expect(
    screen.getByRole('textbox', { name: 'Required subject' }),
  ).toHaveValue(original.required_subject)

  expect(mockedGet).toHaveBeenCalledWith(
    'post_test',
    expect.any(AbortSignal),
    'synthetic-token',
  )
})

test('saves edited fields under the existing post ID', async () => {
  const user = userEvent.setup()
  const onSaved = vi.fn()
  mockedUpdate.mockResolvedValue({
    ...original,
    title: 'Updated title',
  })

  render(<EditPostForm postId="post_test" onSaved={onSaved} />)

  const title = await screen.findByRole('textbox', { name: 'Title' })
  await user.clear(title)
  await user.type(title, '  Updated title  ')
  await user.click(
    screen.getByRole('button', { name: 'Save changes' }),
  )

  expect(await screen.findByText(
    'Post saved. Prepare it for matching again.',
  )).toBeInTheDocument()
  expect(mockedUpdate).toHaveBeenCalledWith(
    'post_test',
    {
      title: 'Updated title',
      content: original.content,
      required_subject: original.required_subject,
    },
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(onSaved).toHaveBeenCalledExactlyOnceWith('post_test')
})

test('failed save preserves edits and allows another attempt', async () => {
  const user = userEvent.setup()
  const onSaved = vi.fn()
  mockedUpdate.mockRejectedValue(new Error('Save unavailable'))

  render(<EditPostForm postId="post_test" onSaved={onSaved} />)

  const title = await screen.findByRole('textbox', { name: 'Title' })
  await user.clear(title)
  await user.type(title, 'Unsaved title')
  await user.click(
    screen.getByRole('button', { name: 'Save changes' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Save unavailable',
  )
  expect(title).toHaveValue('Unsaved title')
  expect(
    screen.getByRole('button', { name: 'Save changes' }),
  ).toBeEnabled()
  expect(onSaved).not.toHaveBeenCalled()
})

test('retries loading after a request error', async () => {
  const user = userEvent.setup()
  mockedGet.mockRejectedValueOnce(new Error('Post unavailable'))

  render(<EditPostForm postId="post_test" onSaved={vi.fn()} />)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Post unavailable',
  )

  await user.click(
    screen.getByRole('button', { name: 'Try loading post again' }),
  )

  expect(
    await screen.findByRole('textbox', { name: 'Title' }),
  ).toHaveValue(original.title)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(mockedGet).toHaveBeenCalledTimes(2)
})

test('blocks duplicate saves and aborts on unmount', async () => {
  let finish!: (post: CreatedPost) => void
  mockedUpdate.mockReturnValue(
    new Promise<CreatedPost>((resolve) => {
      finish = resolve
    }),
  )
  const onSaved = vi.fn()
  const view = render(
    <EditPostForm postId="post_test" onSaved={onSaved} />,
  )

  await screen.findByRole('textbox', { name: 'Title' })

  await act(async () => {
    const form = screen.getByRole('form', { name: 'Edit post' })
    fireEvent.submit(form)
    fireEvent.submit(form)
  })

  expect(mockedUpdate).toHaveBeenCalledOnce()
  expect(
    screen.getByRole('button', { name: 'Saving changes…' }),
  ).toBeDisabled()

  const signal = mockedUpdate.mock.calls[0][2]
  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish(original)
  })

  expect(onSaved).not.toHaveBeenCalled()
})

test('aborts an unfinished load on unmount', async () => {
  let finish!: (post: CreatedPost) => void
  mockedGet.mockReturnValue(
    new Promise<CreatedPost>((resolve) => {
      finish = resolve
    }),
  )

  const view = render(
    <EditPostForm postId="post_test" onSaved={vi.fn()} />,
  )

  await waitFor(() => {
    expect(mockedGet).toHaveBeenCalledOnce()
  })

  const signal = mockedGet.mock.calls[0][1]
  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish(original)
  })

  expect(mockedUpdate).not.toHaveBeenCalled()
})

test('switching keyed editors discards the previous local form', async () => {
  const user = userEvent.setup()
  const onSaved = vi.fn()
  mockedGet.mockImplementation((postId) =>
    Promise.resolve({
      ...original,
      id: postId,
      title: `Title ${postId}`,
    }),
  )

  const view = render(
    <EditPostForm key="first" postId="first" onSaved={onSaved} />,
  )
  const title = await screen.findByDisplayValue('Title first')
  const firstSignal = mockedGet.mock.calls[0][1]

  await user.clear(title)
  await user.type(title, 'Unsaved first title')

  view.rerender(
    <EditPostForm key="second" postId="second" onSaved={onSaved} />,
  )

  expect(
    await screen.findByDisplayValue('Title second'),
  ).toBeInTheDocument()
  expect(
    screen.queryByDisplayValue('Unsaved first title'),
  ).not.toBeInTheDocument()
  expect(firstSignal.aborted).toBe(true)
  expect(mockedUpdate).not.toHaveBeenCalled()
})