import { useEffect, useState } from 'react'
import { getRecommendations } from './api'
import type { RankingResponse } from './api'
import ImagePreview from './ImagePreview'
import ImageAttribution from './ImageAttribution'

const posts = [
  ['post_001', 'Red foxes in urban environments'],
  ['post_002', 'Family behavior in Vulpes vulpes'],
  ['post_003', 'Gray wolves in grassland habitats'],
  ['post_004', 'Keeping dogs active at the beach'],
  ['post_005', 'Black bears in natural habitats'],
  ['post_006', 'The classic Volkswagen Beetle'],
  ['post_007', 'Motor scooters for city travel'],
  ['post_008', 'Serving freshly baked pizza'],
  ['post_009', 'Preparing a colorful vegetable salad'],
  ['post_010', 'Waterfalls and granite cliffs in Yosemite'],
  ['post_011', 'Emperor penguins in Antarctica'],
]

function App() {
  const [postId, setPostId] = useState('post_001')
  const [result, setResult] = useState<RankingResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError('')
      setResult(null)

      try {
        const data = await getRecommendations(
          postId,
          controller.signal,
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
  }, [postId, retry])

  return (
    <main style={{ maxWidth: 900, margin: '40px auto', padding: 24 }}>
      <h1>Image Relevance</h1>
      <p>Select a demo post to find suitable images.</p>

      <label htmlFor="post">Blog post</label>
      <br />
      <select
        id="post"
        value={postId}
        onChange={(event) => setPostId(event.target.value)}
        style={{ padding: 12, marginTop: 8, maxWidth: '100%' }}
      >
        {posts.map(([id, title]) => (
          <option key={id} value={id}>
            {title}
          </option>
        ))}
      </select>

      <section aria-live="polite" aria-busy={loading}>
        {loading && <p>Finding suitable images…</p>}

        {error && (
          <div role="alert">
            <p>{error}</p>
            <button onClick={() => setRetry((value) => value + 1)}>
              Try again
            </button>
          </div>
        )}

        {result && (
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
                  key={image.image_id}
                  imageId={image.image_id}
                  description={image.caption}
                />
                <ImageAttribution
                  key={image.image_id}
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