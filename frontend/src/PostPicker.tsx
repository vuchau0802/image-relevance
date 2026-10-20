import { useEffect, useState } from 'react'
import { getPosts } from './api'
import type { PostSummary } from './api'

interface Props {
  value: string
  onSelect: (postId: string) => void
}

export default function PostPicker({ value, onSelect }: Props) {
  const [posts, setPosts] = useState<PostSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError('')

      try {
        const items = await getPosts(controller.signal)

        if (!controller.signal.aborted) {
          setPosts(items)

          const initial =
            items.find((post) => post.id === 'post_001') ?? items[0]

          onSelect(initial?.id ?? '')
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setError(
            error instanceof Error
              ? error.message
              : 'Could not load posts.',
          )
          setPosts([])
          onSelect('')
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    void load()
    return () => controller.abort()
  }, [onSelect, retry])

  if (loading) {
    return <p role="status">Loading posts…</p>
  }

  if (error) {
    return (
      <div role="alert">
        <p>{error}</p>
        <button onClick={() => setRetry((count) => count + 1)}>
          Reload posts
        </button>
      </div>
    )
  }

  if (posts.length === 0) {
    return <p role="status">No posts are available yet.</p>
  }

  return (
    <>
      <label htmlFor="post">Blog post</label>
      <br />
      <select
        id="post"
        value={value}
        onChange={(event) => onSelect(event.target.value)}
        style={{ padding: 12, marginTop: 8, maxWidth: '100%' }}
      >
        {posts.map((post) => (
          <option key={post.id} value={post.id}>
            {post.title}
          </option>
        ))}
      </select>
    </>
  )
}