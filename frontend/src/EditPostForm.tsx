import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import { getPost, updatePost } from './api'
import type { CreatedPost } from './api'
import { useSessionToken } from './useSessionToken'

export default function EditPostForm({
  postId,
  onSaved,
}: {
  postId: string
  onSaved: (postId: string) => void
}) {
  const getSessionToken = useSessionToken()
  const activeSave = useRef<AbortController | null>(null)
  const [post, setPost] = useState<CreatedPost | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError('')
      setPost(null)
      setSuccess('')

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
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    void load()

    return () => {
      controller.abort()
      activeSave.current?.abort()
    }
  }, [getSessionToken, postId, retry])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (activeSave.current || !post) {
      return
    }

    const values = new FormData(event.currentTarget)
    const controller = new AbortController()
    activeSave.current = controller
    setSaving(true)
    setError('')
    setSuccess('')

    try {
      const updated = await updatePost(
        postId,
        {
          title: String(values.get('title') ?? '').trim(),
          content: String(values.get('content') ?? '').trim(),
          required_subject: String(
            values.get('required_subject') ?? '',
          ).trim(),
        },
        controller.signal,
        await getSessionToken(),
      )

      if (!controller.signal.aborted) {
        setSuccess('Post saved. Prepare it for matching again.')
        onSaved(updated.id)
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(
          error instanceof Error
            ? error.message
            : 'Could not save this post.',
        )
      }
    } finally {
      if (activeSave.current === controller) {
        activeSave.current = null
      }
      if (!controller.signal.aborted) {
        setSaving(false)
      }
    }
  }

  return (
    <section aria-labelledby="edit-post-heading" aria-busy={loading || saving}>
      <h2 id="edit-post-heading">Edit post</h2>

      {loading && <p role="status">Loading post…</p>}
      {error && <p role="alert">{error}</p>}
      {success && <p role="status">{success}</p>}

      {!loading && !post && (
        <button
          type="button"
          onClick={() => setRetry((value) => value + 1)}
        >
          Try loading post again
        </button>
      )}

      {!loading && post && (
        <form aria-label="Edit post" onSubmit={handleSubmit}>
          <fieldset disabled={saving} style={{ border: 0, padding: 0 }}>
            <label htmlFor="edit-post-title">Title</label>
            <input
              id="edit-post-title"
              name="title"
              defaultValue={post.title}
              required
              maxLength={300}
              style={{ display: 'block', width: '100%', padding: 10 }}
            />

            <label htmlFor="edit-post-content">Content</label>
            <textarea
              id="edit-post-content"
              name="content"
              defaultValue={post.content}
              required
              maxLength={10000}
              rows={5}
              style={{ display: 'block', width: '100%', padding: 10 }}
            />

            <label htmlFor="edit-post-subject">Required subject</label>
            <input
              id="edit-post-subject"
              name="required_subject"
              defaultValue={post.required_subject}
              required
              maxLength={200}
              style={{ display: 'block', width: '100%', padding: 10 }}
            />

            <button type="submit" style={{ marginTop: 12 }}>
              {saving ? 'Saving changes…' : 'Save changes'}
            </button>
          </fieldset>
        </form>
      )}
    </section>
  )
}