import { useEffect, useRef, useState } from 'react'

import { deletePost, getPost } from './api'
import type { CreatedPost } from './api'
import { useSessionToken } from './useSessionToken'

export default function DeletePost({
  postId,
  onDeleted,
}: {
  postId: string
  onDeleted: (postId: string) => void
}) {
  const getSessionToken = useSessionToken()
  const activeRequest = useRef<AbortController | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [post, setPost] = useState<CreatedPost | null>(null)
  const [loading, setLoading] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    return () => activeRequest.current?.abort()
  }, [])

  async function openConfirmation() {
    if (activeRequest.current) {
      return
    }

    const controller = new AbortController()
    activeRequest.current = controller
    setConfirming(true)
    setLoading(true)
    setPost(null)
    setError('')

    try {
      const loaded = await getPost(
        postId,
        controller.signal,
        await getSessionToken(),
      )

      if (!controller.signal.aborted) {
        setPost(loaded)
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(
          error instanceof Error
            ? error.message
            : 'Could not load this post.',
        )
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
      }
      if (!controller.signal.aborted) {
        setLoading(false)
      }
    }
  }

  function cancel() {
    activeRequest.current?.abort()
    activeRequest.current = null
    setConfirming(false)
    setLoading(false)
    setPost(null)
    setError('')
  }

  async function confirmDeletion() {
    if (!post || activeRequest.current) {
      return
    }

    const controller = new AbortController()
    activeRequest.current = controller
    setDeleting(true)
    setError('')

    try {
      await deletePost(
        postId,
        controller.signal,
        await getSessionToken(),
      )

      if (!controller.signal.aborted) {
        setConfirming(false)
        setPost(null)
        onDeleted(postId)
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(
          error instanceof Error
            ? error.message
            : 'Could not delete this post.',
        )
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
      }
      if (!controller.signal.aborted) {
        setDeleting(false)
      }
    }
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => void openConfirmation()}
      >
        Delete selected post
      </button>
    )
  }

  return (
    <section
      aria-label="Confirm post deletion"
      aria-busy={loading || deleting}
    >
      <h3>Delete this post?</h3>

      {loading && <p role="status">Loading post details…</p>}

      {post && (
        <>
          <p><strong>{post.title}</strong></p>
          <p>Required subject: {post.required_subject}</p>
          <p>
            This permanently removes the post and its embeddings.
            Uploaded images and historical processing records remain.
          </p>
        </>
      )}

      {error && <p role="alert">{error}</p>}

      {!loading && !post && (
        <button
          type="button"
          onClick={() => void openConfirmation()}
        >
          Try loading post details again
        </button>
      )}

      <button
        type="button"
        disabled={loading || deleting || !post}
        onClick={() => void confirmDeletion()}
      >
        {deleting ? 'Deleting…' : 'Confirm deletion'}
      </button>

      <button
        type="button"
        disabled={deleting}
        onClick={cancel}
      >
        Cancel deletion
      </button>
    </section>
  )
}