import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import { createPost } from './api'
import { useSessionToken } from './useSessionToken'

export default function CreatePostForm({
  onCreated,
}: {
  onCreated: (postId: string) => void
}) {
  const getSessionToken = useSessionToken()
  const activeRequest = useRef<AbortController | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    return () => activeRequest.current?.abort()
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (activeRequest.current) {
      return
    }

    const form = event.currentTarget
    const values = new FormData(form)
    const controller = new AbortController()
    activeRequest.current = controller

    setSaving(true)
    setError('')
    setSuccess('')

    try {
      const post = await createPost(
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
        form.reset()
        setSuccess('Post saved. Matching requires embedding preparation.')
        onCreated(post.id)
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(
          error instanceof Error ? error.message : 'Could not save the post.',
        )
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
      }

      if (!controller.signal.aborted) {
        setSaving(false)
      }
    }
  }

  return (
    <section aria-labelledby="create-post-heading">
      <h2 id="create-post-heading">Create a post</h2>

      <form aria-label="Create post" onSubmit={handleSubmit}>
        <fieldset disabled={saving} style={{ border: 0, padding: 0 }}>
          <label htmlFor="post-title">Title</label>
          <input
            id="post-title"
            name="title"
            required
            maxLength={300}
            style={{ display: 'block', width: '100%', padding: 10 }}
          />

          <label htmlFor="post-content">Content</label>
          <textarea
            id="post-content"
            name="content"
            required
            maxLength={10000}
            rows={5}
            style={{ display: 'block', width: '100%', padding: 10 }}
          />

          <label htmlFor="post-subject">Required subject</label>
          <input
            id="post-subject"
            name="required_subject"
            placeholder="For example: red fox"
            required
            maxLength={200}
            style={{ display: 'block', width: '100%', padding: 10 }}
          />

          <button type="submit" style={{ marginTop: 16 }}>
            {saving ? 'Saving…' : 'Save post'}
          </button>
        </fieldset>

        {error && <p role="alert">{error}</p>}
        {success && <p role="status">{success}</p>}
      </form>
    </section>
  )
}