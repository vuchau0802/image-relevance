import { beforeEach, expect, test, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { getImagesPage, prepareImageEmbedding } from './api'
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
  prepareImageEmbedding: vi.fn(),
  getEmbeddingJob: vi.fn(),
}))

vi.mock('./ImagePreview', () => ({
  default: () => null,
}))

const mockedPage = vi.mocked(getImagesPage)

function image(imageId: string): ImageLibraryItem {
  return {
    image_id: imageId,
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