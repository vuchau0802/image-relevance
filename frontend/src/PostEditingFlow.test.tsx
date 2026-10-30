import { beforeEach, expect, test, vi } from 'vitest'
import {
  act,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import * as api from './api'
import type { CreatedPost } from './api'
import App from './App'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getPosts: vi.fn(),
  getRecommendations: vi.fn(),
  getPost: vi.fn(),
  updatePost: vi.fn(),
  createPost: vi.fn(),
  getImagesPage: vi.fn(),
  uploadImage: vi.fn(),
  startImageAnalysis: vi.fn(),
  getImageAnalysisJob: vi.fn(),
  prepareImageEmbedding: vi.fn(),
  getEmbeddingJob: vi.fn(),
  preparePostEmbedding: vi.fn(),
}))

vi.mock('./ImagePreview', () => ({ default: () => null }))
vi.mock('./ImageAttribution', () => ({ default: () => null }))

const mocked = vi.mocked(api)

const original: CreatedPost = {
  id: 'post_one',
  title: 'Original fox post',
  content: 'An article about red foxes.',
  required_subject: 'red fox',
}
const other: CreatedPost = {
  id: 'post_two',
  title: 'Another post',
  content: 'Another article.',
  required_subject: 'forest',
}

beforeEach(() => {
  vi.resetAllMocks()
  getSessionToken.mockResolvedValue('synthetic-token')
  mocked.getImagesPage.mockResolvedValue({
    items: [],
    next_offset: null,
  })
  mocked.getPosts.mockResolvedValue([original, other])
  mocked.getPost.mockImplementation(async (postId) =>
    postId === original.id ? original : other,
  )
  mocked.getRecommendations.mockImplementation((postId) =>
    Promise.resolve({
      post_id: postId,
      status: 'no_confident_match',
      reason: 'No suitable image.',
      results: [],
    }),
  )
  mocked.preparePostEmbedding.mockResolvedValue({
    job_id: 'prepared_job',
    status: 'completed',
    model: 'test-model',
    dimensions: 768,
    task_type: 'SEMANTIC_SIMILARITY',
    total: 1,
    pending: 0,
    processing: 0,
    completed: 1,
    failed: 0,
  })
})

test('saving refreshes the selected post and resets preparation progress', async () => {
  const user = userEvent.setup()
  const updated = {
    ...original,
    title: 'Updated forest post',
    required_subject: 'forest',
  }
  mocked.updatePost.mockResolvedValue(updated)

  render(<App />)
  await screen.findByRole('heading', { name: 'No confident match' })

  await user.click(
    screen.getByRole('button', { name: 'Prepare for matching' }),
  )
  await screen.findByText(/Preparation: completed/)

  await waitFor(() => {
    expect(mocked.getRecommendations).toHaveBeenCalledTimes(2)
  })

  mocked.getPosts.mockResolvedValue([updated, other])
  mocked.getRecommendations.mockRejectedValue(
    new Error('This post needs an embedding before matching.'),
  )

  await user.click(
    screen.getByRole('button', { name: 'Edit selected post' }),
  )

  const editor = within(
    await screen.findByRole('form', { name: 'Edit post' }),
  )
  await user.clear(editor.getByRole('textbox', { name: 'Title' }))
  await user.type(
    editor.getByRole('textbox', { name: 'Title' }),
    updated.title,
  )
  await user.clear(
    editor.getByRole('textbox', { name: 'Required subject' }),
  )
  await user.type(
    editor.getByRole('textbox', { name: 'Required subject' }),
    'forest',
  )
  await user.click(
    editor.getByRole('button', { name: 'Save changes' }),
  )

  await screen.findByRole('option', { name: updated.title })
  expect(
    screen.getByRole('combobox', { name: 'Blog post' }),
  ).toHaveValue(original.id)
  expect(
    screen.queryByRole('form', { name: 'Edit post' }),
  ).not.toBeInTheDocument()
  expect(
    screen.queryByText(/Preparation: completed/),
  ).not.toBeInTheDocument()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'This post needs an embedding before matching.',
  )
  expect(mocked.updatePost).toHaveBeenCalledWith(
    original.id,
    {
      title: updated.title,
      content: original.content,
      required_subject: 'forest',
    },
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(mocked.getPosts).toHaveBeenCalledTimes(2)
  expect(mocked.getRecommendations).toHaveBeenCalledTimes(3)
})

test('failed save keeps the editor open without refreshing the post', async () => {
  const user = userEvent.setup()
  mocked.updatePost.mockRejectedValue(new Error('Save unavailable'))

  render(<App />)
  await screen.findByRole('heading', { name: 'No confident match' })

  await user.click(
    screen.getByRole('button', { name: 'Edit selected post' }),
  )
  const editor = within(
    await screen.findByRole('form', { name: 'Edit post' }),
  )
  const title = editor.getByRole('textbox', { name: 'Title' })
  await user.clear(title)
  await user.type(title, 'Unsaved title')
  await user.click(
    editor.getByRole('button', { name: 'Save changes' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Save unavailable',
  )
  expect(title).toHaveValue('Unsaved title')
  expect(
    screen.getByRole('option', { name: original.title }),
  ).toBeInTheDocument()
  expect(mocked.getPosts).toHaveBeenCalledOnce()
  expect(mocked.getRecommendations).toHaveBeenCalledOnce()
})

test('switching posts closes the editor and aborts its load', async () => {
  const user = userEvent.setup()
  let finish!: (post: CreatedPost) => void
  const pendingEditor = new Promise<CreatedPost>((resolve) => {
    finish = resolve
  })

  mocked.getPost
    .mockResolvedValueOnce(original)
    .mockImplementation((postId) =>
      postId === original.id
        ? pendingEditor
        : Promise.resolve(other),
    )

  render(<App />)
  await screen.findByRole('heading', { name: 'No confident match' })

  await user.click(
    screen.getByRole('button', { name: 'Edit selected post' }),
  )
  await waitFor(() => {
    expect(mocked.getPost).toHaveBeenCalledTimes(2)
  })
  const signal = mocked.getPost.mock.calls[1][1]

  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Blog post' }),
    other.id,
  )

  expect(signal.aborted).toBe(true)
  expect(
    screen.queryByRole('heading', { name: 'Edit post' }),
  ).not.toBeInTheDocument()

  await act(async () => {
    finish(original)
  })

  expect(
    screen.queryByRole('form', { name: 'Edit post' }),
  ).not.toBeInTheDocument()
  expect(mocked.updatePost).not.toHaveBeenCalled()
})