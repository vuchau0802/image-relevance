import { beforeEach, expect, test, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  getImagesPage,
  prepareImageEmbedding,
  retryEmbeddingPreparation,
  retryImageAnalysis,
  startImageAnalysis,
} from './api'
import type { EmbeddingJob, ImageLibraryItem } from './api'
import ImageLibrary from './ImageLibrary'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  getImagesPage: vi.fn(),
  retryImageAnalysis: vi.fn(),
  startImageAnalysis: vi.fn(),
  getImageAnalysisJob: vi.fn(),
  prepareImageEmbedding: vi.fn(),
  retryEmbeddingPreparation: vi.fn(),
  getEmbeddingJob: vi.fn(),
}))

vi.mock('./ImagePreview', () => ({
  default: () => null,
}))

const mockedPage = vi.mocked(getImagesPage)

function image(imageId: string): ImageLibraryItem {
  return {
    image_id: imageId,
    embedding_ready: false,
    status: 'pending',
    creator: 'Example creator',
    created_at: '2026-01-01T00:00:00Z',
  }
}

beforeEach(() => {
  mockedPage.mockReset()
  getSessionToken.mockReset()
  getSessionToken.mockResolvedValue('synthetic-token')
  vi.mocked(prepareImageEmbedding).mockReset()
  vi.mocked(retryEmbeddingPreparation).mockReset()
  vi.mocked(retryImageAnalysis).mockReset()
  vi.mocked(startImageAnalysis).mockReset()
})

test('loads and displays workspace images', async () => {
  mockedPage.mockResolvedValue({
    items: [image('img_one')],
    next_offset: null,
  })

  render(<ImageLibrary />)

  expect(
    await screen.findByRole('article', {
      name: 'Uploaded image img_one',
    }),
  ).toHaveTextContent('Analysis status: pending')
  expect(screen.getByText('Photo by Example creator')).toBeInTheDocument()

  expect(mockedPage).toHaveBeenCalledWith(
    0,
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(
    screen.queryByRole('button', { name: 'Load more images' }),
  ).not.toBeInTheDocument()
})

test('shows an empty library', async () => {
  mockedPage.mockResolvedValue({ items: [], next_offset: null })

  render(<ImageLibrary />)

  expect(
    await screen.findByText('No images uploaded yet.'),
  ).toBeInTheDocument()
  expect(screen.queryByRole('article')).not.toBeInTheDocument()
})

test('loads another page without duplicating images', async () => {
  const user = userEvent.setup()
  mockedPage
    .mockResolvedValueOnce({
      items: [image('img_one')],
      next_offset: 12,
    })
    .mockResolvedValueOnce({
      items: [image('img_one'), image('img_two')],
      next_offset: null,
    })

  render(<ImageLibrary />)
  await screen.findByRole('article', {
    name: 'Uploaded image img_one',
  })

  await user.click(
    screen.getByRole('button', { name: 'Load more images' }),
  )

  await screen.findByRole('article', {
    name: 'Uploaded image img_two',
  })
  expect(screen.getAllByRole('article')).toHaveLength(2)
  expect(mockedPage).toHaveBeenLastCalledWith(
    12,
    expect.any(AbortSignal),
    'synthetic-token',
  )
})

test('retries a failed initial request', async () => {
  const user = userEvent.setup()
  mockedPage
    .mockRejectedValueOnce(new Error('Images unavailable'))
    .mockResolvedValueOnce({
      items: [image('img_one')],
      next_offset: null,
    })

  render(<ImageLibrary />)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Images unavailable',
  )

  await user.click(
    screen.getByRole('button', {
      name: 'Try loading images again',
    }),
  )

  await screen.findByRole('article', {
    name: 'Uploaded image img_one',
  })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(mockedPage).toHaveBeenCalledTimes(2)
})

test('preserves loaded images when another page fails', async () => {
  const user = userEvent.setup()
  mockedPage
    .mockResolvedValueOnce({
      items: [image('img_one')],
      next_offset: 12,
    })
    .mockRejectedValueOnce(new Error('Next page unavailable'))
    .mockResolvedValueOnce({
      items: [image('img_two')],
      next_offset: null,
    })

  render(<ImageLibrary />)
  await screen.findByRole('article', {
    name: 'Uploaded image img_one',
  })

  await user.click(
    screen.getByRole('button', { name: 'Load more images' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Next page unavailable',
  )
  expect(
    screen.getByRole('article', {
      name: 'Uploaded image img_one',
    }),
  ).toBeInTheDocument()

  await user.click(
    screen.getByRole('button', {
      name: 'Try loading images again',
    }),
  )

  await screen.findByRole('article', {
    name: 'Uploaded image img_two',
  })
  expect(screen.getAllByRole('article')).toHaveLength(2)
  expect(mockedPage.mock.calls.map(([offset]) => offset)).toEqual(
    [0, 12, 12],
  )
})

test('refresh replaces the library starting from page zero', async () => {
  const user = userEvent.setup()
  mockedPage
    .mockResolvedValueOnce({
      items: [image('img_old')],
      next_offset: null,
    })
    .mockResolvedValueOnce({
      items: [image('img_new')],
      next_offset: null,
    })

  render(<ImageLibrary />)
  await screen.findByRole('article', {
    name: 'Uploaded image img_old',
  })

  await user.click(
    screen.getByRole('button', { name: 'Refresh images' }),
  )

  await screen.findByRole('article', {
    name: 'Uploaded image img_new',
  })
  expect(
    screen.queryByRole('article', {
      name: 'Uploaded image img_old',
    }),
  ).not.toBeInTheDocument()
  expect(mockedPage.mock.calls.map(([offset]) => offset)).toEqual([0, 0])
})

test('aborts an outstanding request on unmount', async () => {
  mockedPage.mockReturnValue(new Promise(() => {}))

  const view = render(<ImageLibrary />)

  await waitFor(() => {
    expect(mockedPage).toHaveBeenCalledOnce()
  })

  const signal = mockedPage.mock.calls[0][1]
  view.unmount()

  expect(signal.aborted).toBe(true)
})

test.each([
  ['pending', 'Analyze image'],
  ['processing', 'Analyze image'],
  ['completed', 'Prepare image for matching'],
  ['needs_review', null],
  ['failed', null],
] as const)(
  'shows appropriate controls for analysis status %s',
  async (status, buttonName) => {
    mockedPage.mockResolvedValue({
      items: [{ ...image('img_one'), status }],
      next_offset: null,
    })

    render(<ImageLibrary />)

    await screen.findByRole('article', {
      name: 'Uploaded image img_one',
    })

    if (buttonName) {
      expect(
        screen.getByRole('button', { name: buttonName }),
      ).toBeInTheDocument()
    } else {
      expect(
        screen.queryByRole('button', { name: 'Analyze image' }),
      ).not.toBeInTheDocument()
      expect(
        screen.queryByRole('button', {
          name: 'Prepare image for matching',
        }),
      ).not.toBeInTheDocument()
    }
  },
)

function embeddingJob(
  status: EmbeddingJob['status'],
): EmbeddingJob {
  return {
    job_id: 'library_embedding_job',
    status,
    model: 'test-model',
    dimensions: 768,
    task_type: 'SEMANTIC_SIMILARITY',
    total: 1,
    pending: 0,
    processing: 0,
    completed: status === 'completed' ? 1 : 0,
    failed: status === 'completed' ? 0 : 1,
  }
}

test('successful preparation refreshes the library and notifies App', async () => {
  const user = userEvent.setup()
  const onImageReady = vi.fn()

  mockedPage.mockResolvedValue({
    items: [{ ...image('img_one'), status: 'completed' }],
    next_offset: null,
  })
  vi.mocked(prepareImageEmbedding).mockResolvedValue(
    embeddingJob('completed'),
  )

  render(<ImageLibrary onImageReady={onImageReady} />)

  await user.click(
    await screen.findByRole('button', {
      name: 'Prepare image for matching',
    }),
  )

  await waitFor(() => {
    expect(onImageReady).toHaveBeenCalledOnce()
    expect(mockedPage).toHaveBeenCalledTimes(2)
  })

  expect(prepareImageEmbedding).toHaveBeenCalledWith(
    'img_one',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(mockedPage.mock.calls.map(([offset]) => offset)).toEqual([0, 0])
})

test.each(['failed', 'completed_with_errors'] as const)(
  'preparation outcome %s does not refresh the library',
  async (status) => {
    const user = userEvent.setup()
    const onImageReady = vi.fn()

    mockedPage.mockResolvedValue({
      items: [{ ...image('img_one'), status: 'completed' }],
      next_offset: null,
    })
    vi.mocked(prepareImageEmbedding).mockResolvedValue(
      embeddingJob(status),
    )

    render(<ImageLibrary onImageReady={onImageReady} />)

    await user.click(
      await screen.findByRole('button', {
        name: 'Prepare image for matching',
      }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Image preparation failed',
    )
    expect(onImageReady).not.toHaveBeenCalled()
    expect(mockedPage).toHaveBeenCalledOnce()
  },
)

test('ready images show readiness without another preparation button', async () => {
  mockedPage.mockResolvedValue({
    items: [{
      ...image('img_ready'),
      status: 'completed',
      embedding_ready: true,
    }],
    next_offset: null,
  })

  render(<ImageLibrary />)

  expect(await screen.findByText('Ready for matching.')).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Prepare image for matching' }),
  ).not.toBeInTheDocument()
  expect(prepareImageEmbedding).not.toHaveBeenCalled()
})

test('completed preparation reloads readiness and removes its button', async () => {
  const user = userEvent.setup()
  const onImageReady = vi.fn()
  mockedPage
    .mockResolvedValueOnce({
      items: [{ ...image('img_one'), status: 'completed' }],
      next_offset: null,
    })
    .mockResolvedValue({
      items: [{
        ...image('img_one'),
        status: 'completed',
        embedding_ready: true,
      }],
      next_offset: null,
    })
  vi.mocked(prepareImageEmbedding).mockResolvedValue(embeddingJob('completed'))

  render(<ImageLibrary onImageReady={onImageReady} />)

  await user.click(
    await screen.findByRole('button', { name: 'Prepare image for matching' }),
  )

  expect(await screen.findByText('Ready for matching.')).toBeInTheDocument()
  expect(onImageReady).toHaveBeenCalledOnce()
  expect(mockedPage).toHaveBeenCalledTimes(2)
  expect(
    screen.queryByRole('button', { name: 'Prepare image for matching' }),
  ).not.toBeInTheDocument()
})


function loadFailedImage(failedJobId: string | null) {
  mockedPage.mockResolvedValue({
    items: [{
      ...image('img_failed'),
      status: 'failed',
      failed_analysis_job_id: failedJobId,
    }],
    next_offset: null,
  })
}

function completedAnalysis() {
  return {
    job_id: 'retry_job',
    status: 'completed' as const,
    total: 1,
    pending: 0,
    processing: 0,
    completed: 1,
    needs_review: 0,
    failed: 0,
  }
}

test('loaded failed image retries its discovered job', async () => {
  const user = userEvent.setup()
  loadFailedImage('failed_job')
  vi.mocked(retryImageAnalysis).mockResolvedValue(
    completedAnalysis(),
  )

  render(<ImageLibrary />)

  const retryButton = await screen.findByRole('button', {
    name: 'Retry image analysis',
  })
  expect(retryImageAnalysis).not.toHaveBeenCalled()

  await user.click(retryButton)

  expect(
    await screen.findByText(
      /Analysis complete\. Image embedding preparation/,
    ),
  ).toBeInTheDocument()

  expect(retryImageAnalysis).toHaveBeenCalledExactlyOnceWith(
    'img_failed',
    'failed_job',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(startImageAnalysis).not.toHaveBeenCalled()
})

test('loaded failed image preserves retry after a request error', async () => {
  const user = userEvent.setup()
  loadFailedImage('failed_job')
  vi.mocked(retryImageAnalysis)
    .mockRejectedValueOnce(new Error('Service unavailable'))
    .mockResolvedValueOnce(completedAnalysis())

  render(<ImageLibrary />)

  await user.click(
    await screen.findByRole('button', {
      name: 'Retry image analysis',
    }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Service unavailable',
  )

  await user.click(
    screen.getByRole('button', {
      name: 'Retry image analysis',
    }),
  )

  await screen.findByText(
    /Analysis complete\. Image embedding preparation/,
  )

  expect(
    vi.mocked(retryImageAnalysis).mock.calls.map(
      (call) => call[1],
    ),
  ).toEqual(['failed_job', 'failed_job'])
  expect(startImageAnalysis).not.toHaveBeenCalled()
})

test('failed image without a job explains why retry is unavailable', async () => {
  loadFailedImage(null)

  render(<ImageLibrary />)

  expect(
    await screen.findByText(/No retryable analysis job was found/),
  ).toBeInTheDocument()

  expect(
    screen.queryByRole('button', {
      name: 'Retry image analysis',
    }),
  ).not.toBeInTheDocument()
  expect(retryImageAnalysis).not.toHaveBeenCalled()
  expect(startImageAnalysis).not.toHaveBeenCalled()
})


test('discovered preparation failure retries and refreshes the library', async () => {
  const user = userEvent.setup()
  const onImageReady = vi.fn()

  mockedPage
    .mockResolvedValueOnce({
      items: [{
        ...image('img_retry'),
        status: 'completed',
        failed_preparation_job_id: 'failed_preparation_job',
      }],
      next_offset: null,
    })
    .mockResolvedValue({
      items: [{
        ...image('img_retry'),
        status: 'completed',
        embedding_ready: true,
        failed_preparation_job_id: null,
      }],
      next_offset: null,
    })

  vi.mocked(retryEmbeddingPreparation).mockResolvedValue(
    embeddingJob('completed'),
  )

  render(<ImageLibrary onImageReady={onImageReady} />)

  const retry = await screen.findByRole('button', {
    name: 'Retry image preparation',
  })
  expect(retryEmbeddingPreparation).not.toHaveBeenCalled()

  await user.click(retry)

  expect(
    await screen.findByText('Ready for matching.'),
  ).toBeInTheDocument()

  expect(retryEmbeddingPreparation).toHaveBeenCalledExactlyOnceWith(
    'image',
    'img_retry',
    'failed_preparation_job',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(prepareImageEmbedding).not.toHaveBeenCalled()
  expect(mockedPage).toHaveBeenCalledTimes(2)
  expect(onImageReady).toHaveBeenCalledOnce()
  expect(
    screen.queryByRole('button', {
      name: 'Retry image preparation',
    }),
  ).not.toBeInTheDocument()
})

test('discovered preparation failure preserves retry after a request error', async () => {
  const user = userEvent.setup()
  const onImageReady = vi.fn()

  mockedPage.mockResolvedValue({
    items: [{
      ...image('img_retry'),
      status: 'completed',
      failed_preparation_job_id: 'failed_preparation_job',
    }],
    next_offset: null,
  })

  vi.mocked(retryEmbeddingPreparation).mockRejectedValue(
    new Error('Preparation service unavailable'),
  )

  render(<ImageLibrary onImageReady={onImageReady} />)

  await user.click(
    await screen.findByRole('button', {
      name: 'Retry image preparation',
    }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Preparation service unavailable',
  )
  expect(onImageReady).not.toHaveBeenCalled()
  expect(mockedPage).toHaveBeenCalledOnce()

  await user.click(
    screen.getByRole('button', {
      name: 'Retry image preparation',
    }),
  )

  await waitFor(() => {
    expect(retryEmbeddingPreparation).toHaveBeenCalledTimes(2)
    expect(
      screen.getByRole('button', {
        name: 'Retry image preparation',
      }),
    ).toBeEnabled()
  })

  expect(
    vi.mocked(retryEmbeddingPreparation).mock.calls.map(
      (call) => call[2],
    ),
  ).toEqual([
    'failed_preparation_job',
    'failed_preparation_job',
  ])
  expect(prepareImageEmbedding).not.toHaveBeenCalled()
  expect(onImageReady).not.toHaveBeenCalled()
  expect(mockedPage).toHaveBeenCalledOnce()
})
