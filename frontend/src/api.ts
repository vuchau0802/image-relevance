import { apiFetch } from './http'
export interface RankedImage {
  image_id: string
  subject: string
  caption: string
  similarity: number
}

export interface RankingResponse {
  post_id: string
  status:
    | 'matched'
    | 'no_confident_match'
    | 'incomplete'
    | 'unsupported_subject'
  reason: string
  results: RankedImage[]
}

export async function getRecommendations(
  postId: string,
  signal: AbortSignal,
  accessToken: string,
): Promise<RankingResponse> {
  const response = await apiFetch(
    `/posts/${encodeURIComponent(postId)}/images?top=5`,
    signal,
    accessToken,
  )

  if (!response.ok) {
    const messages: Record<number, string> = {
      404: 'This post was not found.',
      409: 'This post needs an embedding before matching.',
    }

    throw new Error(
      messages[response.status] ??
        `Could not load recommendations (${response.status}).`,
    )
  }

  return response.json()
}

export interface PostSummary {
  id: string
  title: string
  required_subject: string
}

interface PostPage {
  items: PostSummary[]
  next_offset: number | null
}

export async function getPosts(
  signal: AbortSignal,
  accessToken: string,
): Promise<PostSummary[]> {
  const posts: PostSummary[] = []
  let offset = 0

  while (true) {
    const response = await apiFetch(
      `/posts?offset=${offset}&limit=50`,
      signal,
      accessToken,
    )

    if (!response.ok) {
      throw new Error(`Could not load posts (${response.status}).`)
    }

    const page: PostPage = await response.json()
    posts.push(...page.items)

    if (page.next_offset === null) {
      return posts
    }

    if (
      !Number.isInteger(page.next_offset) ||
      page.next_offset <= offset
    ) {
      throw new Error('Invalid post pagination response.')
    }

    offset = page.next_offset
  }
}

export interface PostCreateInput {
  title: string
  content: string
  required_subject: string
}

export interface CreatedPost extends PostSummary {
  content: string
}

export async function createPost(
  payload: PostCreateInput,
  signal: AbortSignal,
  accessToken: string,
): Promise<CreatedPost> {
  const response = await apiFetch('/posts', signal, accessToken, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    throw new Error(
      response.status === 422
        ? 'Check the required fields and their lengths.'
        : `Could not save the post (${response.status}).`,
    )
  }

  return response.json()
}

export interface EmbeddingJob {
  job_id: string
  status:
    | 'queued'
    | 'running'
    | 'completed'
    | 'completed_with_errors'
    | 'failed'
  model: string
  dimensions: number
  task_type: string
  total: number
  pending: number
  processing: number
  completed: number
  failed: number
}

export async function preparePostEmbedding(
  postId: string,
  signal: AbortSignal,
  accessToken: string,
): Promise<EmbeddingJob> {
  const response = await apiFetch(
    `/posts/${encodeURIComponent(postId)}/embedding-job`,
    signal,
    accessToken,
    { method: 'POST' },
  )

  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? 'Post not found.'
        : `Could not prepare this post (${response.status}).`,
    )
  }

  return response.json()
}

export async function getEmbeddingJob(
  jobId: string,
  signal: AbortSignal,
  accessToken: string,
): Promise<EmbeddingJob> {
  const response = await apiFetch(
    `/embedding-jobs/${encodeURIComponent(jobId)}`,
    signal,
    accessToken,
  )

  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? 'Preparation job not found.'
        : `Could not load preparation progress (${response.status}).`,
    )
  }

  return response.json()
}

export interface ImageUploadResult {
  image_id: string
  status:
    | 'pending'
    | 'processing'
    | 'completed'
    | 'needs_review'
    | 'failed'
}

export async function uploadImage(
  file: File,
  creator: string,
  signal: AbortSignal,
  accessToken: string,
): Promise<ImageUploadResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('creator', creator.trim())

  const response = await apiFetch(
    '/images',
    signal,
    accessToken,
    {
      method: 'POST',
      body: form,
    },
  )

  if (!response.ok) {
    const message =
      response.status === 413
        ? 'The upload is too large. Choose a JPEG under 10 MiB.'
        : response.status === 422
          ? 'Choose a valid JPEG up to 20 million pixels and provide its creator.'
          : response.status === 401
            ? 'Please sign in again.'
            : `Could not upload the image (${response.status}).`

    throw new Error(message)
  }

  return response.json()
}