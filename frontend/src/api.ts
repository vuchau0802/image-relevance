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
): Promise<RankingResponse> {
  const response = await fetch(
    `/api/posts/${encodeURIComponent(postId)}/images?top=5`,
    {
      headers: { 'X-Tenant-ID': 'demo' },
      signal,
    },
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