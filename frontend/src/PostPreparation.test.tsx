import { beforeEach, expect, test, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  getPost,
  preparePostEmbedding,
  retryEmbeddingPreparation,
} from './api'
import type { CreatedPost, EmbeddingJob } from './api'
import PostPreparation from './PostPreparation'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getPost: vi.fn(),
  preparePostEmbedding: vi.fn(),
  retryEmbeddingPreparation: vi.fn(),
  getEmbeddingJob: vi.fn(),
}))

function post(
  id = 'post_test',
  failedJobId: string | null = null,
): CreatedPost {
  return {
    id,
    title: 'Forest article',
    content: 'A path through a green forest.',
    required_subject: 'forest',
    failed_preparation_job_id: failedJobId,
  }
}

function completedJob(): EmbeddingJob {
  return {
    job_id: 'retry_job',
    status: 'completed',
    model: 'test-model',
    dimensions: 768,
    task_type: 'SEMANTIC_SIMILARITY',
    total: 1,
    pending: 0,
    processing: 0,
    completed: 1,
    failed: 0,
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  getSessionToken.mockResolvedValue('synthetic-token')
})

test('loads the failed preparation and retries the discovered job', async () => {
  const user = userEvent.setup()
  const onReady = vi.fn()
  vi.mocked(getPost).mockResolvedValue(
    post('post_test', 'failed_job'),
  )
  vi.mocked(retryEmbeddingPreparation).mockResolvedValue(
    completedJob(),
  )

  render(
    <PostPreparation postId="post_test" onReady={onReady} />,
  )

  const retry = await screen.findByRole('button', {
    name: 'Retry post preparation',
  })

  expect(getPost).toHaveBeenCalledExactlyOnceWith(
    'post_test',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(retryEmbeddingPreparation).not.toHaveBeenCalled()

  await user.click(retry)

  await waitFor(() => {
    expect(onReady).toHaveBeenCalledOnce()
  })
  expect(retryEmbeddingPreparation).toHaveBeenCalledExactlyOnceWith(
    'post',
    'post_test',
    'failed_job',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(preparePostEmbedding).not.toHaveBeenCalled()
})

test('status loading failure allows another attempt without starting preparation', async () => {
  const user = userEvent.setup()
  vi.mocked(getPost)
    .mockRejectedValueOnce(new Error('Status unavailable'))
    .mockResolvedValueOnce(post())

  render(
    <PostPreparation postId="post_test" onReady={vi.fn()} />,
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Status unavailable',
  )
  expect(preparePostEmbedding).not.toHaveBeenCalled()
  expect(retryEmbeddingPreparation).not.toHaveBeenCalled()

  await user.click(
    screen.getByRole('button', {
      name: 'Retry loading preparation status',
    }),
  )

  expect(
    await screen.findByRole('button', {
      name: 'Prepare for matching',
    }),
  ).toBeEnabled()
  expect(getPost).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('switching keyed posts aborts loading and ignores the old response', async () => {
  let finish!: (value: CreatedPost) => void
  vi.mocked(getPost)
    .mockReturnValueOnce(
      new Promise<CreatedPost>((resolve) => {
        finish = resolve
      }),
    )
    .mockResolvedValueOnce(post('post_two'))

  const onReady = vi.fn()
  const view = render(
    <PostPreparation
      key="post_one"
      postId="post_one"
      onReady={onReady}
    />,
  )

  await waitFor(() => {
    expect(getPost).toHaveBeenCalledOnce()
  })
  const signal = vi.mocked(getPost).mock.calls[0][1]

  view.rerender(
    <PostPreparation
      key="post_two"
      postId="post_two"
      onReady={onReady}
    />,
  )

  await screen.findByRole('button', {
    name: 'Prepare for matching',
  })
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish(post('post_one', 'old_failed_job'))
  })

  expect(
    screen.queryByRole('button', {
      name: 'Retry post preparation',
    }),
  ).not.toBeInTheDocument()
  expect(
    screen.getByRole('button', {
      name: 'Prepare for matching',
    }),
  ).toBeEnabled()
  expect(onReady).not.toHaveBeenCalled()
  expect(retryEmbeddingPreparation).not.toHaveBeenCalled()
})

test('a response for another post does not expose preparation controls', async () => {
  vi.mocked(getPost).mockResolvedValue(
    post('different_post', 'different_failed_job'),
  )

  render(
    <PostPreparation postId="post_test" onReady={vi.fn()} />,
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'The requested post could not be loaded.',
  )
  expect(
    screen.queryByRole('button', {
      name: 'Retry post preparation',
    }),
  ).not.toBeInTheDocument()
  expect(preparePostEmbedding).not.toHaveBeenCalled()
  expect(retryEmbeddingPreparation).not.toHaveBeenCalled()
})