import { beforeEach, expect, test, vi } from 'vitest'
import {
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import * as api from './api'
import type { CreatedPost, RankingResponse } from './api'
import App from './App'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getPosts: vi.fn(),
  getPost: vi.fn(),
  updatePost: vi.fn(),
  deletePost: vi.fn(),
  createPost: vi.fn(),
  getRecommendations: vi.fn(),
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

const first: CreatedPost = {
  id: 'post_one',
  title: 'First post',
  content: 'First article content.',
  required_subject: 'red fox',
}
const second: CreatedPost = {
  id: 'post_two',
  title: 'Second post',
  content: 'Second article content.',
  required_subject: 'forest',
}

function ranking(postId: string): RankingResponse {
  return {
    post_id: postId,
    status: 'matched',
    reason: 'A suitable image was found.',
    results: [{
      image_id: `img_${postId}`,
      subject: 'Test subject',
      caption: `Suggested image for ${postId}.`,
      similarity: 0.9,
    }],
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  getSessionToken.mockResolvedValue('synthetic-token')
  mocked.getImagesPage.mockResolvedValue({
    items: [],
    next_offset: null,
  })
  mocked.getPosts.mockResolvedValue([first, second])
  mocked.getPost.mockImplementation((postId) =>
    Promise.resolve(postId === first.id ? first : second),
  )
  mocked.getRecommendations.mockImplementation((postId) =>
    Promise.resolve(ranking(postId)),
  )
  mocked.deletePost.mockResolvedValue(undefined)
})

async function openConfirmation(
  user: ReturnType<typeof userEvent.setup>,
  title: string,
) {
  await user.click(
    screen.getByRole('button', { name: 'Delete selected post' }),
  )
  const region = await screen.findByRole('region', {
    name: 'Confirm post deletion',
  })
  await within(region).findByText(title)
  return within(region)
}

test('deleting the selected post refreshes the list and selects another', async () => {
  const user = userEvent.setup()
  mocked.getPosts
    .mockResolvedValueOnce([first, second])
    .mockResolvedValue([second])

  render(<App />)
  await screen.findByText(`Suggested image for ${first.id}.`)

  const confirmation = await openConfirmation(user, first.title)
  await user.click(
    confirmation.getByRole('button', { name: 'Confirm deletion' }),
  )

  await waitFor(() => {
    expect(
      screen.queryByRole('option', { name: first.title }),
    ).not.toBeInTheDocument()
  })

  expect(
    screen.getByRole('combobox', { name: 'Blog post' }),
  ).toHaveValue(second.id)
  expect(
    await screen.findByText(`Suggested image for ${second.id}.`),
  ).toBeInTheDocument()
  expect(
    screen.queryByText(`Suggested image for ${first.id}.`),
  ).not.toBeInTheDocument()

  expect(mocked.deletePost).toHaveBeenCalledExactlyOnceWith(
    first.id,
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(mocked.getPosts).toHaveBeenCalledTimes(2)
})

test('deleting the last post clears selection and recommendations', async () => {
  const user = userEvent.setup()
  mocked.getPosts
    .mockResolvedValueOnce([first])
    .mockResolvedValue([])

  render(<App />)
  await screen.findByText(`Suggested image for ${first.id}.`)

  const confirmation = await openConfirmation(user, first.title)
  await user.click(
    confirmation.getByRole('button', { name: 'Confirm deletion' }),
  )

  expect(
    await screen.findByText('No posts are available yet.'),
  ).toBeInTheDocument()
  expect(
    screen.queryByRole('combobox', { name: 'Blog post' }),
  ).not.toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Delete selected post' }),
  ).not.toBeInTheDocument()
  expect(
    screen.queryByText(`Suggested image for ${first.id}.`),
  ).not.toBeInTheDocument()
  expect(mocked.getRecommendations).toHaveBeenCalledOnce()
})

test('failed deletion preserves the selected post and its results', async () => {
  const user = userEvent.setup()
  mocked.deletePost.mockRejectedValue(
    new Error('Post preparation is queued or processing.'),
  )

  render(<App />)
  await screen.findByText(`Suggested image for ${first.id}.`)

  const confirmation = await openConfirmation(user, first.title)
  await user.click(
    confirmation.getByRole('button', { name: 'Confirm deletion' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Post preparation is queued or processing.',
  )
  expect(
    screen.getByRole('combobox', { name: 'Blog post' }),
  ).toHaveValue(first.id)
  expect(
    screen.getByText(`Suggested image for ${first.id}.`),
  ).toBeInTheDocument()
  expect(mocked.getPosts).toHaveBeenCalledOnce()
  expect(mocked.getRecommendations).toHaveBeenCalledOnce()
})

test('switching posts resets confirmation to the newly selected post', async () => {
  const user = userEvent.setup()

  render(<App />)
  await screen.findByText(`Suggested image for ${first.id}.`)
  await openConfirmation(user, first.title)

  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Blog post' }),
    second.id,
  )

  expect(
    screen.queryByRole('region', { name: 'Confirm post deletion' }),
  ).not.toBeInTheDocument()

  const confirmation = await openConfirmation(user, second.title)
  expect(confirmation.queryByText(first.title)).not.toBeInTheDocument()

  await user.click(
    confirmation.getByRole('button', { name: 'Cancel deletion' }),
  )

  expect(mocked.deletePost).not.toHaveBeenCalled()
})