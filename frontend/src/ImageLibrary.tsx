import { useEffect, useState } from 'react'
import { getImagesPage } from './api'
import type { ImageLibraryItem } from './api'
import ImagePreview from './ImagePreview'
import { useSessionToken } from './useSessionToken'
import AnalyzeImage from './AnalyzeImage'
import PrepareImage from './PrepareImage'
import DeleteImage from './DeleteImage'

export default function ImageLibrary({
  onImageReady,
}: {
  onImageReady?: () => void
}) {
  const getSessionToken = useSessionToken()
  const [items, setItems] = useState<ImageLibraryItem[]>([])
  const [offset, setOffset] = useState(0)
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [retry, setRetry] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError('')

      try {
        const page = await getImagesPage(
          offset,
          controller.signal,
          await getSessionToken(),
        )

        if (!controller.signal.aborted) {
          setItems((previous) => {
            const combined = offset === 0
              ? page.items
              : [...previous, ...page.items]

            return Array.from(
              new Map(
                combined.map((item) => [item.image_id, item]),
              ).values(),
            )
          })
          setNextOffset(page.next_offset)
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setError(
            error instanceof Error
              ? error.message
              : 'Could not load your images.',
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
  }, [getSessionToken, offset, retry])

  function refresh() {
    setItems([])
    setNextOffset(null)
    setOffset(0)
    setRetry((value) => value + 1)
  }

  return (
    <section
      aria-labelledby="image-library-heading"
      aria-busy={loading}
    >
      <h2 id="image-library-heading">Your images</h2>

      <button
        type="button"
        disabled={loading}
        onClick={refresh}
      >
        Refresh images
      </button>

      {loading && <p role="status">Loading images…</p>}

      {error && (
        <div role="alert">
          <p>{error}</p>
          <button
            type="button"
            onClick={() => setRetry((value) => value + 1)}
          >
            Try loading images again
          </button>
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <p>No images uploaded yet.</p>
      )}

      {items.map((image) => (
        <article
          key={image.image_id}
          aria-label={`Uploaded image ${image.image_id}`}
          style={{
            border: '1px solid #888',
            borderRadius: 12,
            padding: 16,
            marginTop: 16,
          }}
        >
          <ImagePreview
            imageId={image.image_id}
            description={`Uploaded image ${image.image_id}`}
          />
          <p>{image.image_id}</p>
          <p>Photo by {image.creator}</p>
          <p>Analysis status: {image.status}</p>
          <p>
            {image.status !== 'completed'
              ? 'Not ready for matching.'
              : image.embedding_ready
                ? 'Ready for matching.'
                : 'Embedding preparation needed.'}
          </p>

          {(image.status === 'pending' ||
            image.status === 'processing') && (
            <AnalyzeImage
              imageId={image.image_id}
              onImageReady={() => {
                onImageReady?.()
                refresh()
              }}
            />
          )}

          {image.status === 'completed' && !image.embedding_ready && (
            <PrepareImage
              key={`preparation-${image.image_id}-${image.failed_preparation_job_id ?? 'new'}`}
              imageId={image.image_id}
              initialFailedJobId={image.failed_preparation_job_id}
              onReady={() => {
                onImageReady?.()
                refresh()
              }}
            />
          )}

          {image.status === 'needs_review' && (
            <p>This image needs review before matching.</p>
          )}

          {image.status === 'failed' && (
            image.failed_analysis_job_id ? (
              <AnalyzeImage
                key={`retry-${image.image_id}-${image.failed_analysis_job_id}`}
                imageId={image.image_id}
                initialFailedJobId={image.failed_analysis_job_id}
                onImageReady={() => {
                  onImageReady?.()
                  refresh()
                }}
              />
            ) : (
              <p>
                Image analysis failed. No retryable analysis job
                was found. Refresh your images to check again.
              </p>
            )
          )}
          <DeleteImage
            imageId={image.image_id}
            creator={image.creator}
            onDeleted={() => {
              refresh()
              onImageReady?.()
            }}
          />
        </article>
      ))}

      {nextOffset !== null && !error && (
        <button
          type="button"
          disabled={loading}
          onClick={() => setOffset(nextOffset)}
        >
          Load more images
        </button>
      )}
    </section>
  )
}