import { useSessionToken } from './useSessionToken'
import { useCallback, useEffect, useState } from 'react'
import { getRecommendations } from './api'
import type { RankingResponse } from './api'
import ImagePreview from './ImagePreview'
import ImageAttribution from './ImageAttribution'
import PostPicker from './PostPicker'
import CreatePostForm from './CreatePostForm'
import EditPostForm from './EditPostForm'
import PreparePost from './PreparePost'
import UploadImageForm from './UploadImageForm'
import ImageLibrary from './ImageLibrary'
import DeletePost from './DeletePost'

function App() {
  const getSessionToken = useSessionToken()
  const [postId, setPostId] = useState('')
  const [postsVersion, setPostsVersion] = useState(0)
  const [libraryVersion, setLibraryVersion] = useState(0)
  const [result, setResult] = useState<RankingResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [editing, setEditing] = useState(false)

  const selectPost = useCallback((selectedId: string) => {
    setPostId(selectedId)
    setEditing(false)
  }, [])

  useEffect(() => {
    if (!postId) {
      return
    }

    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError('')
      setResult(null)

      try {
        const data = await getRecommendations(
          postId,
          controller.signal,
          await getSessionToken(),
        )

        if (!controller.signal.aborted) {
          setResult(data)
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setError(
            error instanceof Error
              ? error.message
              : 'Could not load recommendations.',
          )
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    void load()
    return () => controller.abort()
  }, [getSessionToken, postId, retry])

  return (
    <main style={{ maxWidth: 900, margin: '40px auto', padding: 24 }}>
      <h1>Image Relevance</h1>
      <p>Select a post to find suitable images.</p>
      <UploadImageForm
        onUploaded={() => {
          setLibraryVersion((value) => value + 1)
        }}
        onImageReady={() => {
          setRetry((value) => value + 1)
          setLibraryVersion((value) => value + 1)
        }}
      />
      <ImageLibrary
        key={`images-${libraryVersion}`}
        onImageReady={() => setRetry((value) => value + 1)}
      />
      <CreatePostForm
        onCreated={(createdId) => {
          setPostId(createdId)
          setEditing(false)
          setPostsVersion((version) => version + 1)
        }}
      />

      <PostPicker
        key={`posts-${postsVersion}`}
        value={postId}
        onSelect={selectPost}
      />

      {postId && (
        <button
          type="button"
          aria-expanded={editing}
          onClick={() => setEditing((value) => !value)}
        >
          {editing ? 'Close editor' : 'Edit selected post'}
        </button>
      )}

      {postId && editing && (
        <EditPostForm
          key={postId}
          postId={postId}
          onSaved={(savedId) => {
            setPostId(savedId)
            setEditing(false)
            setPostsVersion((value) => value + 1)
            setResult(null)
            setRetry((value) => value + 1)
          }}
        />
      )}

      {postId && !editing && (
        <DeletePost
          key={`delete-post-${postId}-${postsVersion}`}
          postId={postId}
          onDeleted={() => {
            setPostId('')
            setEditing(false)
            setResult(null)
            setError('')
            setLoading(false)
            setPostsVersion((value) => value + 1)
          }}
        />
      )}

      <section aria-live="polite" aria-busy={loading}>
        {postId && loading && <p>Finding suitable images…</p>}
        {postId && (
          <PreparePost
            key={`post-preparation-${postId}-${postsVersion}`}
            postId={postId}
            onReady={() => setRetry((value) => value + 1)}
          />
        )}

        {postId && error && (
          <div role="alert">
            <p>{error}</p>
            <button onClick={() => setRetry((value) => value + 1)}>
              Try again
            </button>
          </div>
        )}

        {postId && result && result.post_id === postId && (
          <>
            <h2>
              {result.status === 'matched'
                ? 'Suggested images'
                : result.status === 'incomplete'
                  ? 'Results are incomplete'
                  : result.status === 'unsupported_subject'
                    ? 'Subject is not supported'
                    : 'No confident match'}
            </h2>

            <p>{result.reason}</p>

            {result.status === 'incomplete' && (
              <p>Any images below are provisional suggestions.</p>
            )}

            {result.results.map((image) => (
              <article
                key={image.image_id}
                style={{
                  border: '1px solid #888',
                  borderRadius: 12,
                  padding: 20,
                  marginTop: 16,
                }}
              >
                <ImagePreview
                  imageId={image.image_id}
                  description={image.caption}
                />
                <ImageAttribution
                  imageId={image.image_id}
                />
                <h3>{image.subject}</h3>
                <p>{image.caption}</p>
                <p>
                  {image.image_id} · Similarity:{' '}
                  {image.similarity.toFixed(3)}
                </p>
              </article>
            ))}

            {result.status === 'matched' && (
              <p>
                Similarity measures text alignment; it is not a
                probability that the image is correct.
              </p>
            )}
          </>
        )}
      </section>
    </main>
  )
}

export default App
