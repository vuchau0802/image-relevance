import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

import {
  getImageAnalysisJob,
  retryImageAnalysis,
  startImageAnalysis,
} from './api'
import type { ImageAnalysisJob } from './api'
import AnalyzeImage from './AnalyzeImage'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getImageAnalysisJob: vi.fn(),
  retryImageAnalysis: vi.fn(),
  startImageAnalysis: vi.fn(),
}))

const mockedStart = vi.mocked(startImageAnalysis)
const mockedProgress = vi.mocked(getImageAnalysisJob)
const mockedRetry = vi.mocked(retryImageAnalysis)

function job(
  status: ImageAnalysisJob['status'],
  overrides: Partial<ImageAnalysisJob> = {},
): ImageAnalysisJob {
  return {
    job_id: 'analysis_test',
    status,
    total: 1,
    pending: status === 'queued' ? 1 : 0,
    processing: status === 'running' ? 1 : 0,
    completed: status === 'completed' ? 1 : 0,
    needs_review: 0,
    failed:
      status === 'failed' ||
      status === 'completed_with_errors'
        ? 1
        : 0,
    ...overrides,
  }
}

beforeEach(() => {
  mockedStart.mockReset()
  mockedProgress.mockReset()
  mockedRetry.mockReset()
  getSessionToken.mockReset()
  getSessionToken.mockResolvedValue('synthetic-token')
})

async function clickAnalyze() {
  await act(async () => {
    fireEvent.click(
      screen.getByRole('button', { name: 'Analyze image' }),
    )
  })
}

test('reports completed analysis without claiming matching is ready', async () => {
  mockedStart.mockResolvedValue(job('completed'))

  render(<AnalyzeImage imageId="img_test" />)
  await clickAnalyze()

  expect(mockedStart).toHaveBeenCalledWith(
    'img_test',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(screen.getByRole('status')).toHaveTextContent(
    'Image embedding preparation is still required before matching.',
  )
  expect(mockedProgress).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: /^Analy/ })).toBeEnabled()
})

test('polls queued and running jobs until completion', async () => {
  vi.useFakeTimers()

  try {
    mockedStart.mockResolvedValue(job('queued'))
    mockedProgress
      .mockResolvedValueOnce(job('running'))
      .mockResolvedValueOnce(job('completed'))

    render(<AnalyzeImage imageId="img_test" />)
    await clickAnalyze()

    expect(screen.getByRole('status')).toHaveTextContent('queued')
    expect(screen.getByRole('button', { name: /^Analy/ })).toBeDisabled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(screen.getByRole('status')).toHaveTextContent('running')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(screen.getByRole('status')).toHaveTextContent(
      'Analysis complete.',
    )
    expect(mockedProgress).toHaveBeenCalledTimes(2)
    expect(mockedProgress).toHaveBeenLastCalledWith(
      'analysis_test',
      expect.any(AbortSignal),
      'synthetic-token',
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    expect(mockedProgress).toHaveBeenCalledTimes(2)
  } finally {
    vi.useRealTimers()
  }
})

test.each(['completed', 'completed_with_errors'] as const)(
  'explains review requirements for %s',
  async (status) => {
    mockedStart.mockResolvedValue(
      job(status, {
        completed: 0,
        needs_review: 1,
        failed: 0,
      }),
    )

    render(<AnalyzeImage imageId="img_test" />)
    await clickAnalyze()

    expect(screen.getByRole('status')).toHaveTextContent(
      'Analysis requires review',
    )
    expect(
      screen.queryByText(/Analysis complete\. Image embedding/),
    ).not.toBeInTheDocument()
    expect(mockedProgress).not.toHaveBeenCalled()
  },
)

test.each(['failed', 'completed_with_errors'] as const)(
  'reports terminal failure for %s',
  async (status) => {
    mockedStart.mockResolvedValue(job(status))

    render(<AnalyzeImage imageId="img_test" />)
    await clickAnalyze()

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Analysis did not complete successfully.',
    )
    expect(mockedProgress).not.toHaveBeenCalled()
    expect(
      screen.getByRole('button', { name: 'Retry image analysis' }),
    ).toBeEnabled()
  },
)

test('allows another attempt after a request error', async () => {
  mockedStart
    .mockRejectedValueOnce(new Error('Service unavailable'))
    .mockResolvedValueOnce(job('completed'))

  render(<AnalyzeImage imageId="img_test" />)
  await clickAnalyze()

  expect(screen.getByRole('alert')).toHaveTextContent(
    'Service unavailable',
  )

  await clickAnalyze()

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(
    'Analysis complete.',
  )
})

test('blocks duplicate submissions and aborts on unmount', async () => {
  let finish!: (value: ImageAnalysisJob) => void
  mockedStart.mockReturnValue(
    new Promise<ImageAnalysisJob>((resolve) => {
      finish = resolve
    }),
  )

  const view = render(<AnalyzeImage imageId="img_test" />)

  await act(async () => {
    const button = screen.getByRole('button', { name: /^Analy/ })
    fireEvent.click(button)
    fireEvent.click(button)
  })

  expect(mockedStart).toHaveBeenCalledOnce()

  const signal = mockedStart.mock.calls[0][1]
  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish(job('queued'))
  })

  expect(mockedProgress).not.toHaveBeenCalled()
})

async function clickRetry() {
  await act(async () => {
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Retry image analysis',
      }),
    )
  })
}

test('retries the failed job and recovers successfully', async () => {
  mockedStart.mockResolvedValue(
    job('failed', { job_id: 'failed_job' }),
  )
  mockedRetry.mockResolvedValue(
    job('completed', { job_id: 'retry_job' }),
  )

  render(<AnalyzeImage imageId="img_test" />)
  await clickAnalyze()
  await clickRetry()

  expect(mockedRetry).toHaveBeenCalledExactlyOnceWith(
    'img_test',
    'failed_job',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(mockedStart).toHaveBeenCalledOnce()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(
    'Analysis complete.',
  )
})

test('a failed retry request preserves the failed job for another attempt', async () => {
  mockedStart.mockResolvedValue(
    job('failed', { job_id: 'failed_job' }),
  )
  mockedRetry
    .mockRejectedValueOnce(new Error('Service unavailable'))
    .mockResolvedValueOnce(
      job('completed', { job_id: 'retry_job' }),
    )

  render(<AnalyzeImage imageId="img_test" />)
  await clickAnalyze()
  await clickRetry()

  expect(screen.getByRole('alert')).toHaveTextContent(
    'Service unavailable',
  )
  expect(
    screen.getByRole('button', {
      name: 'Retry image analysis',
    }),
  ).toBeEnabled()

  await clickRetry()

  expect(mockedRetry).toHaveBeenCalledTimes(2)
  expect(mockedRetry.mock.calls.map((call) => call[1])).toEqual([
    'failed_job',
    'failed_job',
  ])
  expect(mockedStart).toHaveBeenCalledOnce()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('a failed retry job becomes the target of the next retry', async () => {
  mockedStart.mockResolvedValue(
    job('failed', { job_id: 'original_job' }),
  )
  mockedRetry
    .mockResolvedValueOnce(
      job('failed', { job_id: 'first_retry_job' }),
    )
    .mockResolvedValueOnce(
      job('completed', { job_id: 'second_retry_job' }),
    )

  render(<AnalyzeImage imageId="img_test" />)
  await clickAnalyze()
  await clickRetry()
  await clickRetry()

  expect(mockedRetry.mock.calls.map((call) => call[1])).toEqual([
    'original_job',
    'first_retry_job',
  ])
  expect(screen.getByRole('status')).toHaveTextContent(
    'Analysis complete.',
  )
})

test('blocks duplicate retries and aborts on unmount', async () => {
  mockedStart.mockResolvedValue(
    job('failed', { job_id: 'failed_job' }),
  )

  let finish!: (value: ImageAnalysisJob) => void
  mockedRetry.mockReturnValue(
    new Promise<ImageAnalysisJob>((resolve) => {
      finish = resolve
    }),
  )

  const view = render(<AnalyzeImage imageId="img_test" />)
  await clickAnalyze()

  await act(async () => {
    const button = screen.getByRole('button', {
      name: 'Retry image analysis',
    })
    fireEvent.click(button)
    fireEvent.click(button)
  })

  expect(mockedRetry).toHaveBeenCalledOnce()
  expect(
    screen.getByRole('button', { name: 'Analyzing…' }),
  ).toBeDisabled()

  const signal = mockedRetry.mock.calls[0][2]
  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish(job('queued', { job_id: 'retry_job' }))
  })

  expect(mockedProgress).not.toHaveBeenCalled()
})
