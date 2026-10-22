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