import { useEffect, useState } from 'react'
import { getPost } from './api'
import type { CreatedPost } from './api'
import PreparePost from './PreparePost'
import { useSessionToken } from './useSessionToken'

export default function PostPreparation({
  postId,
  onReady,
}: {
  postId: string
  onReady: () => void
}) {
  const getSessionToken = useSessionToken()
  const [post, setPost] = useState<CreatedPost | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    async function load() {
      setPost(null)
      setError('')

      try {
        const token = await getSessionToken()
        if (controller.signal.aborted) return

        const loaded = await getPost(
          postId,
          controller.signal,
          token,
        )

        if (!controller.signal.aborted) {
          if (loaded.id !== postId) {
            throw new Error('The requested post could not be loaded.')
          }
          setPost(loaded)
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setError(
            error instanceof Error
              ? error.message
              : 'Could not load post preparation status.',
          )
        }
      }
    }

    void load()
    return () => controller.abort()
  }, [getSessionToken, postId, retry])

  if (error) {
    return (
      <section aria-label="Post preparation status">
        <p role="alert">{error}</p>
        <button
          type="button"
          onClick={() => setRetry((value) => value + 1)}
        >
          Retry loading preparation status
        </button>
      </section>
    )
  }

  if (!post || post.id !== postId) {
    return <p role="status">Loading post preparation status…</p>
  }

  return (
    <PreparePost
      key={`${post.id}-${post.failed_preparation_job_id ?? 'new'}`}
      postId={post.id}
      initialFailedJobId={post.failed_preparation_job_id}
      onReady={onReady}
    />
  )
}