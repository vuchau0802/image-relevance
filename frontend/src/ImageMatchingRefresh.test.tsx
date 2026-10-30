import { beforeEach, expect, test, vi } from 'vitest'
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import * as api from './api'
import type { EmbeddingJob, RankingResponse } from './api'
import App from './App'
import PrepareImage from './PrepareImage'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  deleteImage: vi.fn(),
  getImagesPage: vi.fn(),
  getPosts: vi.fn(),
  getPost: vi.fn(),
  getRecommendations: vi.fn(),
  createPost: vi.fn(),
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

function embeddingJob(
  status: EmbeddingJob['status'],
): EmbeddingJob {
  return {
    job_id: 'embedding_job',
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

function ranking(matched: boolean): RankingResponse {
  return {
    post_id: 'post_test',
    status: matched ? 'matched' : 'no_confident_match',
    reason: matched ? 'A suitable image was found.' : 'No suitable image.',
    results: matched
      ? [{
          image_id: 'img_uploaded',
          subject: 'red fox',
          caption: 'A synthetic red fox image.',
          similarity: 0.9,
        }]
      : [],
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  mocked.getPost.mockImplementation(async (postId) => ({
    id: postId,
    title: 'Selected fox post',
    content: 'Synthetic red fox content.',
    required_subject: 'red fox',
    failed_preparation_job_id: null,
  }))
  mocked.getImagesPage.mockResolvedValue({
    items: [],
    next_offset: null,
  })
  getSessionToken.mockResolvedValue('synthetic-token')

  mocked.getPosts.mockResolvedValue([{
    id: 'post_test',
    title: 'Selected fox post',
    required_subject: 'red fox',
  }])

  mocked.getRecommendations
    .mockResolvedValueOnce(ranking(false))
    .mockResolvedValue(ranking(true))

  mocked.uploadImage.mockResolvedValue({
    image_id: 'img_uploaded',
    status: 'pending',
  })

  mocked.startImageAnalysis.mockResolvedValue({
    job_id: 'analysis_job',
    status: 'completed',
    total: 1,
    pending: 0,
    processing: 0,
    completed: 1,
    needs_review: 0,
    failed: 0,
  })
})

test.each([
  'completed',
  'failed',
  'completed_with_errors',
] as const)(
  'image preparation outcome %s controls recommendation refresh',
  async (status) => {
    const user = userEvent.setup()
    mocked.prepareImageEmbedding.mockResolvedValue(
      embeddingJob(status),
    )

    render(<App />)

    await screen.findByRole('heading', { name: 'No confident match' })

    await user.upload(
      screen.getByLabelText('JPEG image'),
      new File(['synthetic JPEG'], 'fox.jpg', {
        type: 'image/jpeg',
      }),
    )
    await user.type(
      screen.getByRole('textbox', { name: 'Image creator' }),
      'Example creator',
    )

    // Submit directly because of jsdom's uploaded-file validity issue.
    await act(async () => {
      fireEvent.submit(
        screen.getByRole('form', { name: 'Upload image' }),
      )
    })

    await user.click(
      await screen.findByRole('button', { name: 'Analyze image' }),
    )
    await user.click(
      await screen.findByRole('button', {
        name: 'Prepare image for matching',
      }),
    )

    if (status === 'completed') {
      expect(
        await screen.findByRole('heading', { name: 'Suggested images' }),
      ).toBeInTheDocument()

      await waitFor(() => {
        expect(mocked.getRecommendations).toHaveBeenCalledTimes(2)
      })
      expect(mocked.getRecommendations).toHaveBeenLastCalledWith(
        'post_test',
        expect.any(AbortSignal),
        'synthetic-token',
      )
    } else {
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Image preparation failed',
      )
      expect(mocked.getRecommendations).toHaveBeenCalledOnce()
      expect(
        screen.getByRole('heading', { name: 'No confident match' }),
      ).toBeInTheDocument()
    }

    expect(
      screen.getByRole('combobox', { name: 'Blog post' }),
    ).toHaveValue('post_test')
    expect(mocked.getPosts).toHaveBeenCalledOnce()
  },
)

test('completion after unmount does not notify App', async () => {
  let finish!: (value: EmbeddingJob) => void
  mocked.prepareImageEmbedding.mockReturnValue(
    new Promise<EmbeddingJob>((resolve) => {
      finish = resolve
    }),
  )
  const onReady = vi.fn()

  const view = render(
    <PrepareImage imageId="img_uploaded" onReady={onReady} />,
  )

  await act(async () => {
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Prepare image for matching',
      }),
    )
  })

  const signal = mocked.prepareImageEmbedding.mock.calls[0][1]
  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish(embeddingJob('completed'))
  })

  expect(onReady).not.toHaveBeenCalled()
})

test('successful upload refreshes the library without reranking the post', async () => {
  const user = userEvent.setup()

  mocked.getImagesPage
    .mockResolvedValueOnce({
      items: [],
      next_offset: null,
    })
    .mockResolvedValue({
      items: [{
        image_id: 'img_uploaded',
        status: 'pending',
        creator: 'Example creator',
        created_at: '2026-01-01T00:00:00Z',
        embedding_ready: false,
      }],
      next_offset: null,
    })

  render(<App />)

  await screen.findByText('No images uploaded yet.')
  await screen.findByRole('heading', { name: 'No confident match' })

  await user.upload(
    screen.getByLabelText('JPEG image'),
    new File(['synthetic JPEG'], 'fox.jpg', {
      type: 'image/jpeg',
    }),
  )
  await user.type(
    screen.getByRole('textbox', { name: 'Image creator' }),
    'Example creator',
  )

  await act(async () => {
    fireEvent.submit(
      screen.getByRole('form', { name: 'Upload image' }),
    )
  })

  expect(
    await screen.findByRole('article', {
      name: 'Uploaded image img_uploaded',
    }),
  ).toBeInTheDocument()

  expect(mocked.getImagesPage).toHaveBeenCalledTimes(2)
  expect(mocked.getRecommendations).toHaveBeenCalledOnce()
  expect(
    screen.getByRole('combobox', { name: 'Blog post' }),
  ).toHaveValue('post_test')
})


test('successful image deletion refreshes the library and recommendations', async () => {
  const user = userEvent.setup()

  mocked.getImagesPage
    .mockResolvedValueOnce({
      items: [{
        image_id: 'img_uploaded',
        status: 'completed',
        creator: 'Example creator',
        created_at: '2026-01-01T00:00:00Z',
        embedding_ready: true,
      }],
      next_offset: null,
    })
    .mockResolvedValue({
      items: [],
      next_offset: null,
    })

  mocked.getRecommendations
    .mockReset()
    .mockResolvedValueOnce(ranking(true))
    .mockResolvedValue(ranking(false))
  mocked.deleteImage.mockResolvedValue(undefined)

  render(<App />)

  await screen.findByRole('article', {
    name: 'Uploaded image img_uploaded',
  })
  await screen.findByRole('heading', {
    name: 'Suggested images',
  })

  await user.click(
    screen.getByRole('button', { name: 'Delete image' }),
  )
  await user.click(
    screen.getByRole('button', {
      name: 'Confirm image deletion',
    }),
  )

  await screen.findByText('No images uploaded yet.')
  await screen.findByRole('heading', {
    name: 'No confident match',
  })

  expect(
    screen.queryByRole('article', {
      name: 'Uploaded image img_uploaded',
    }),
  ).not.toBeInTheDocument()
  expect(mocked.deleteImage).toHaveBeenCalledExactlyOnceWith(
    'img_uploaded',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(mocked.getImagesPage).toHaveBeenCalledTimes(2)
  expect(mocked.getRecommendations).toHaveBeenCalledTimes(2)
  expect(
    screen.getByRole('combobox', { name: 'Blog post' }),
  ).toHaveValue('post_test')
})

test('failed image deletion preserves the library and recommendations', async () => {
  const user = userEvent.setup()

  mocked.getImagesPage.mockResolvedValue({
    items: [{
      image_id: 'img_uploaded',
      status: 'completed',
      creator: 'Example creator',
      created_at: '2026-01-01T00:00:00Z',
      embedding_ready: true,
    }],
    next_offset: null,
  })
  mocked.getRecommendations
    .mockReset()
    .mockResolvedValue(ranking(true))
  mocked.deleteImage.mockRejectedValue(
    new Error('Image processing is still running.'),
  )

  render(<App />)

  await screen.findByRole('article', {
    name: 'Uploaded image img_uploaded',
  })
  await screen.findByRole('heading', {
    name: 'Suggested images',
  })

  await user.click(
    screen.getByRole('button', { name: 'Delete image' }),
  )
  await user.click(
    screen.getByRole('button', {
      name: 'Confirm image deletion',
    }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Image processing is still running.',
  )
  expect(
    screen.getByRole('article', {
      name: 'Uploaded image img_uploaded',
    }),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('heading', { name: 'Suggested images' }),
  ).toBeInTheDocument()
  expect(mocked.getImagesPage).toHaveBeenCalledOnce()
  expect(mocked.getRecommendations).toHaveBeenCalledOnce()
})
