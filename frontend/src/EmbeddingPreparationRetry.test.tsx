import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

import {
  getEmbeddingJob,
  prepareImageEmbedding,
  preparePostEmbedding,
  retryEmbeddingPreparation,
} from './api'
import type { EmbeddingJob } from './api'
import PrepareImage from './PrepareImage'
import PreparePost from './PreparePost'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getEmbeddingJob: vi.fn(),
  prepareImageEmbedding: vi.fn(),
  preparePostEmbedding: vi.fn(),
  retryEmbeddingPreparation: vi.fn(),
}))

function job(
  status: EmbeddingJob['status'],
  id = 'failed_job',
): EmbeddingJob {
  return {
    job_id: id,
    status,
    model: 'test-model',
    dimensions: 768,
    task_type: 'SEMANTIC_SIMILARITY',
    total: 1,
    pending: 0,
    processing: 0,
    completed: status === 'completed' ? 1 : 0,
    failed: status === 'failed' ? 1 : 0,
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  getSessionToken.mockResolvedValue('synthetic-token')
  vi.mocked(prepareImageEmbedding).mockResolvedValue(job('failed'))
  vi.mocked(preparePostEmbedding).mockResolvedValue(job('failed'))
})

async function clickButton(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name }))
  })
}

function showPreparation(
  source: 'image' | 'post',
  onReady: () => void,
) {
  return render(
    source === 'image'
      ? <PrepareImage imageId="source_test" onReady={onReady} />
      : <PreparePost postId="source_test" onReady={onReady} />,
  )
}

const sources = ['image', 'post'] as const

test.each(sources)('%s preparation retries and reports success', async (source) => {
  const onReady = vi.fn()
  vi.mocked(retryEmbeddingPreparation).mockResolvedValue(
    job('completed', 'retry_job'),
  )

  showPreparation(source, onReady)
  await clickButton(
    source === 'image'
      ? 'Prepare image for matching'
      : 'Prepare for matching',
  )
  expect(onReady).not.toHaveBeenCalled()

  await clickButton(`Retry ${source} preparation`)

  expect(retryEmbeddingPreparation).toHaveBeenCalledExactlyOnceWith(
    source,
    'source_test',
    'failed_job',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(onReady).toHaveBeenCalledOnce()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test.each(sources)('%s preparation preserves retry after a request error', async (source) => {
  const onReady = vi.fn()
  vi.mocked(retryEmbeddingPreparation)
    .mockRejectedValueOnce(new Error('Service unavailable'))
    .mockResolvedValueOnce(job('completed', 'retry_job'))

  showPreparation(source, onReady)
  await clickButton(
    source === 'image'
      ? 'Prepare image for matching'
      : 'Prepare for matching',
  )
  await clickButton(`Retry ${source} preparation`)

  expect(screen.getByRole('alert')).toHaveTextContent(
    'Service unavailable',
  )
  expect(onReady).not.toHaveBeenCalled()

  await clickButton(`Retry ${source} preparation`)

  expect(
    vi.mocked(retryEmbeddingPreparation).mock.calls.map(
      (call) => call[2],
    ),
  ).toEqual(['failed_job', 'failed_job'])
  expect(onReady).toHaveBeenCalledOnce()
})

test.each(sources)('%s preparation blocks duplicate retries and aborts on unmount', async (source) => {
  let finish!: (value: EmbeddingJob) => void
  vi.mocked(retryEmbeddingPreparation).mockReturnValue(
    new Promise<EmbeddingJob>((resolve) => {
      finish = resolve
    }),
  )
  const onReady = vi.fn()
  const view = showPreparation(source, onReady)

  await clickButton(
    source === 'image'
      ? 'Prepare image for matching'
      : 'Prepare for matching',
  )

  await act(async () => {
    const button = screen.getByRole('button', {
      name: `Retry ${source} preparation`,
    })
    fireEvent.click(button)
    fireEvent.click(button)
  })

  expect(retryEmbeddingPreparation).toHaveBeenCalledOnce()
  expect(screen.getByRole('button')).toBeDisabled()

  const signal = vi.mocked(retryEmbeddingPreparation).mock.calls[0][3]
  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish(job('completed', 'retry_job'))
  })

  expect(onReady).not.toHaveBeenCalled()
  expect(getEmbeddingJob).not.toHaveBeenCalled()
})