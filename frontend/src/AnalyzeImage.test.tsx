import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

import {
  getImageAnalysisJob,
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
  startImageAnalysis: vi.fn(),
}))

const mockedStart = vi.mocked(startImageAnalysis)
const mockedProgress = vi.mocked(getImageAnalysisJob)

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
  expect(screen.getByRole('button')).toBeEnabled()
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
    expect(screen.getByRole('button')).toBeDisabled()

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
    expect(screen.getByRole('button')).toBeEnabled()
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
    const button = screen.getByRole('button')
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