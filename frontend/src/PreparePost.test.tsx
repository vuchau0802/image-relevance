import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import {
  getEmbeddingJob,
  preparePostEmbedding,
} from './api'
import type { EmbeddingJob } from './api'
import PreparePost from './PreparePost'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getEmbeddingJob: vi.fn(),
  preparePostEmbedding: vi.fn(),
}))

const mockedPrepare = vi.mocked(preparePostEmbedding)
const mockedProgress = vi.mocked(getEmbeddingJob)

function job(
  status: EmbeddingJob['status'],
): EmbeddingJob {
  return {
    job_id: 'job_test',
    status,
    model: 'test-model',
    dimensions: 768,
    task_type: 'SEMANTIC_SIMILARITY',
    total: 1,
    pending: status === 'queued' ? 1 : 0,
    processing: status === 'running' ? 1 : 0,
    completed: status === 'completed' ? 1 : 0,
    failed:
      status === 'failed' ||
      status === 'completed_with_errors'
        ? 1
        : 0,
  }
}

beforeEach(() => {
  mockedPrepare.mockReset()
  mockedProgress.mockReset()
  getSessionToken.mockReset()
  getSessionToken.mockResolvedValue('synthetic-token')
})

test('an already completed job refreshes recommendations', async () => {
  mockedPrepare.mockResolvedValue(job('completed'))
  const onReady = vi.fn()

  render(
    <PreparePost postId="post_test" onReady={onReady} />,
  )

  await act(async () => {
    fireEvent.click(
      screen.getByRole('button', { name: 'Prepare for matching' }),
    )
  })

  expect(mockedPrepare).toHaveBeenCalledWith(
    'post_test',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(onReady).toHaveBeenCalledOnce()
  expect(mockedProgress).not.toHaveBeenCalled()
})

test('polls a queued job until it completes', async () => {
  vi.useFakeTimers()

  try {
    mockedPrepare.mockResolvedValue(job('queued'))
    mockedProgress
      .mockResolvedValueOnce(job('running'))
      .mockResolvedValueOnce(job('completed'))
    const onReady = vi.fn()

    render(
      <PreparePost postId="post_test" onReady={onReady} />,
    )

    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: 'Prepare for matching' }),
      )
    })

    expect(screen.getByRole('button')).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('queued')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(screen.getByRole('status')).toHaveTextContent('running')
    expect(onReady).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(mockedProgress).toHaveBeenCalledTimes(2)
    expect(mockedProgress).toHaveBeenLastCalledWith(
      'job_test',
      expect.any(AbortSignal),
      'synthetic-token',
    )
    expect(onReady).toHaveBeenCalledOnce()
    expect(screen.getByRole('button')).toBeEnabled()
  } finally {
    vi.useRealTimers()
  }
})

test.each(['failed', 'completed_with_errors'] as const)(
  'shows a terminal failure for %s',
  async (status) => {
    mockedPrepare.mockResolvedValue(job(status))
    const onReady = vi.fn()

    render(
      <PreparePost postId="post_test" onReady={onReady} />,
    )

    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: 'Prepare for matching' }),
      )
    })

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Preparation failed',
    )
    expect(onReady).not.toHaveBeenCalled()
    expect(mockedProgress).not.toHaveBeenCalled()
    expect(screen.getByRole('button')).toBeEnabled()
  },
)

test('shows a request error and allows another attempt', async () => {
  mockedPrepare
    .mockRejectedValueOnce(new Error('Service unavailable'))
    .mockResolvedValueOnce(job('completed'))
  const onReady = vi.fn()

  render(
    <PreparePost postId="post_test" onReady={onReady} />,
  )

  await act(async () => {
    fireEvent.click(screen.getByRole('button'))
  })

  expect(screen.getByRole('alert')).toHaveTextContent(
    'Service unavailable',
  )
  expect(screen.getByRole('button')).toBeEnabled()

  await act(async () => {
    fireEvent.click(screen.getByRole('button'))
  })

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(onReady).toHaveBeenCalledOnce()
})

test('blocks duplicate clicks and ignores completion after unmount', async () => {
  let finish!: (value: EmbeddingJob) => void
  mockedPrepare.mockReturnValue(
    new Promise<EmbeddingJob>((resolve) => {
      finish = resolve
    }),
  )
  const onReady = vi.fn()

  const view = render(
    <PreparePost postId="post_test" onReady={onReady} />,
  )

  await act(async () => {
    const button = screen.getByRole('button')
    fireEvent.click(button)
    fireEvent.click(button)
  })

  expect(mockedPrepare).toHaveBeenCalledOnce()
  const signal = mockedPrepare.mock.calls[0][1]

  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish(job('completed'))
  })

  expect(onReady).not.toHaveBeenCalled()
  expect(mockedProgress).not.toHaveBeenCalled()
})