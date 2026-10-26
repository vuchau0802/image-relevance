import { beforeEach, expect, test, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import App from './App'
import { createPost, getImagesPage, getPosts, getRecommendations } from './api'
import type { RankingResponse } from './api'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getImagesPage: vi.fn(),
  getPosts: vi.fn(),
  getRecommendations: vi.fn(),
  createPost: vi.fn(),
}))

// These tests focus on recommendations, not image fetching.
vi.mock('./ImagePreview', () => ({ default: () => null }))
vi.mock('./ImageAttribution', () => ({ default: () => null }))

const mockedPosts = vi.mocked(getPosts)
const mockedRecommendations = vi.mocked(getRecommendations)
const mockedCreatePost = vi.mocked(createPost)

function ranking(
  postId: string,
  matched: boolean,
): RankingResponse {
  return {
    post_id: postId,
    status: matched ? 'matched' : 'no_confident_match',
    reason: matched
      ? 'Images passed the matching checks.'
      : 'No suitable image was found.',
    results: matched
      ? [{
          image_id: 'img_test',
          subject: 'red fox',
          caption: 'A synthetic fox image.',
          similarity: 0.9,
        }]
      : [],
  }
}

beforeEach(() => {
  vi.mocked(getImagesPage).mockReset()
  vi.mocked(getImagesPage).mockResolvedValue({
    items: [],
    next_offset: null,
  })
  getSessionToken.mockReset()
  getSessionToken.mockResolvedValue('synthetic-session-token')
  mockedPosts.mockReset()
  mockedRecommendations.mockReset()
  mockedCreatePost.mockReset()
  mockedPosts.mockResolvedValue([
    {
      id: 'post_001',
      title: 'Fox post',
      required_subject: 'red fox',
    },
    {
      id: 'post_011',
      title: 'Penguin post',
      required_subject: 'emperor penguin',
    },
  ])
})

test('shows a no-match explanation without result cards', async () => {
  mockedRecommendations.mockResolvedValue(
    ranking('post_001', false),
  )

  render(<App />)

  expect(
    await screen.findByRole('heading', {
      name: 'No confident match',
    }),
  ).toBeInTheDocument()

  expect(
    screen.getByText('No suitable image was found.'),
  ).toBeInTheDocument()

  expect(screen.queryByRole('article')).not.toBeInTheDocument()
})

test('retries a failed recommendation request successfully', async () => {
  const user = userEvent.setup()

  mockedRecommendations
    .mockRejectedValueOnce(
      new Error('Could not load recommendations (502).'),
    )
    .mockResolvedValueOnce(ranking('post_001', true))

  render(<App />)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not load recommendations (502).',
  )

  await user.click(
    screen.getByRole('button', { name: 'Try again' }),
  )

  expect(
    await screen.findByRole('heading', {
      name: 'Suggested images',
    }),
  ).toBeInTheDocument()

  expect(screen.getByText('A synthetic fox image.')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(mockedRecommendations).toHaveBeenCalledTimes(2)
})

test('ignores an old response after switching posts', async () => {
  const user = userEvent.setup()
  let finishFirst:
    | ((value: RankingResponse) => void)
    | undefined

  const firstRequest = new Promise<RankingResponse>((resolve) => {
    finishFirst = resolve
  })

  mockedRecommendations.mockImplementation((postId) => {
    if (postId === 'post_001') {
      return firstRequest
    }

    return Promise.resolve(ranking(postId, false))
  })

  render(<App />)

  await waitFor(() => {
    expect(mockedRecommendations).toHaveBeenCalledWith(
      'post_001',
      expect.any(AbortSignal),
      'synthetic-session-token',
    )
  })

  const firstSignal = mockedRecommendations.mock.calls[0][1]

  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Blog post' }),
    'post_011',
  )

  expect(
    await screen.findByRole('heading', {
      name: 'No confident match',
    }),
  ).toBeInTheDocument()

  expect(firstSignal.aborted).toBe(true)

  const resolve = finishFirst
  if (!resolve) {
    throw new Error('First request was not initialized')
  }

  // Simulate a transport that delivers a response despite cancellation.
  await act(async () => {
    resolve(ranking('post_001', true))
    await firstRequest
  })

  expect(
    screen.getByRole('heading', { name: 'No confident match' }),
  ).toBeInTheDocument()

  expect(
    screen.queryByRole('heading', { name: 'Suggested images' }),
  ).not.toBeInTheDocument()

  expect(screen.queryByRole('article')).not.toBeInTheDocument()
})

test('saving a post refreshes the dropdown and selects it', async () => {
  const user = userEvent.setup()

  const existing = {
    id: 'post_001',
    title: 'Existing post',
    required_subject: 'red fox',
  }

  const created = {
    id: 'post_created',
    title: 'New private fox article',
    content: 'An article about urban red foxes.',
    required_subject: 'red fox',
  }

  mockedPosts
    .mockResolvedValueOnce([existing])
    .mockResolvedValue([existing, created])

  mockedCreatePost.mockResolvedValue(created)

  mockedRecommendations.mockImplementation((postId) =>
    Promise.resolve(ranking(postId, false)),
  )

  render(<App />)

  expect(
    await screen.findByRole('option', { name: 'Existing post' }),
  ).toBeInTheDocument()

  await user.type(
    screen.getByRole('textbox', { name: 'Title' }),
    created.title,
  )
  await user.type(
    screen.getByRole('textbox', { name: 'Content' }),
    created.content,
  )
  await user.type(
    screen.getByRole('textbox', { name: 'Required subject' }),
    created.required_subject,
  )

  await user.click(
    screen.getByRole('button', { name: 'Save post' }),
  )

  expect(
    await screen.findByRole('option', { name: created.title }),
  ).toBeInTheDocument()

  expect(
    screen.getByRole('combobox', { name: 'Blog post' }),
  ).toHaveValue(created.id)

  expect(mockedCreatePost).toHaveBeenCalledOnce()
  expect(mockedPosts).toHaveBeenCalledTimes(2)

  await waitFor(() => {
    expect(mockedRecommendations).toHaveBeenLastCalledWith(
      created.id,
      expect.any(AbortSignal),
      'synthetic-session-token',
    )
  })
})