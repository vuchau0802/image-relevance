import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import {
  getEmbeddingJob,
  prepareImageEmbedding,
} from './api'
import type { EmbeddingJob } from './api'
import PrepareImage from './PrepareImage'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getEmbeddingJob: vi.fn(),
  prepareImageEmbedding: vi.fn(),
}))

const mockedPrepare = vi.mocked(prepareImageEmbedding)
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

test('an already completed job reports the image embedding is ready', async () => {
  mockedPrepare.mockResolvedValue(job('completed'))


  render(
    <PrepareImage imageId="img_test" />,
  )

  await act(async () => {
    fireEvent.click(
      screen.getByRole('button', { name: 'Prepare image for matching' }),
    )
  })

  expect(mockedPrepare).toHaveBeenCalledWith(
    'img_test',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(screen.getByRole('status')).toHaveTextContent(
      'Image embedding is ready.',
    )
  expect(mockedProgress).not.toHaveBeenCalled()
})

test('polls a queued job until it completes', async () => {
  vi.useFakeTimers()

  try {
    mockedPrepare.mockResolvedValue(job('queued'))
    mockedProgress
      .mockResolvedValueOnce(job('running'))
      .mockResolvedValueOnce(job('completed'))


    render(
      <PrepareImage imageId="img_test" />,
    )

    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: 'Prepare image for matching' }),
      )
    })

    expect(screen.getByRole('button')).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('queued')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(screen.getByRole('status')).toHaveTextContent('running')
    expect(screen.queryByText(/Image embedding is ready/)).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(mockedProgress).toHaveBeenCalledTimes(2)
    expect(mockedProgress).toHaveBeenLastCalledWith(
      'job_test',
      expect.any(AbortSignal),
      'synthetic-token',
    )
    expect(screen.getByRole('status')).toHaveTextContent(
      'Image embedding is ready.',
    )
    expect(screen.getByRole('button')).toBeEnabled()
  } finally {
    vi.useRealTimers()
  }
})

test.each(['failed', 'completed_with_errors'] as const)(
  'shows a terminal failure for %s',
  async (status) => {
    mockedPrepare.mockResolvedValue(job(status))


    render(
      <PrepareImage imageId="img_test" />,
    )

    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: 'Prepare image for matching' }),
      )
    })

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Image preparation failed',
    )
    expect(screen.queryByText(/Image embedding is ready/)).not.toBeInTheDocument()
    expect(mockedProgress).not.toHaveBeenCalled()
    expect(screen.getByRole('button')).toBeEnabled()
  },
)

test('shows a request error and allows another attempt', async () => {
  mockedPrepare
    .mockRejectedValueOnce(new Error('Service unavailable'))
    .mockResolvedValueOnce(job('completed'))


  render(
    <PrepareImage imageId="img_test" />,
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
  expect(screen.getByRole('status')).toHaveTextContent(
      'Image embedding is ready.',
    )
})

test('blocks duplicate clicks and ignores completion after unmount', async () => {
  let finish!: (value: EmbeddingJob) => void
  mockedPrepare.mockReturnValue(
    new Promise<EmbeddingJob>((resolve) => {
      finish = resolve
    }),
  )


  const view = render(
    <PrepareImage imageId="img_test" />,
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

  expect(screen.queryByText(/Image embedding is ready/)).not.toBeInTheDocument()
  expect(mockedProgress).not.toHaveBeenCalled()
})