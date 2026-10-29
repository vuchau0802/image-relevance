import { useEffect, useRef, useState } from 'react'
import { deleteImage } from './api'
import { useSessionToken } from './useSessionToken'

export default function DeleteImage({
  imageId,
  creator,
  onDeleted,
}: {
  imageId: string
  creator: string
  onDeleted: (imageId: string) => void
}) {
  const getSessionToken = useSessionToken()
  const activeRequest = useRef<AbortController | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    return () => activeRequest.current?.abort()
  }, [])

  async function confirmDeletion() {
    if (activeRequest.current) return

    const controller = new AbortController()
    activeRequest.current = controller
    setDeleting(true)
    setError('')

    try {
      const token = await getSessionToken()
      if (controller.signal.aborted) return

      await deleteImage(imageId, controller.signal, token)

      if (!controller.signal.aborted) {
        onDeleted(imageId)
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(
          error instanceof Error
            ? error.message
            : 'Could not delete this image.',
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
        onClick={() => {
          setError('')
          setConfirming(true)
        }}
      >
        Delete image
      </button>
    )
  }

  return (
    <section
      aria-label={`Confirm deletion of image ${imageId}`}
      aria-busy={deleting}
    >
      <h3>Delete this image?</h3>
      <p>{imageId}</p>
      <p>Photo by {creator}</p>
      <p>
        This permanently removes the image from your library and
        matching results. Its stored file is queued for removal.
      </p>

      {error && <p role="alert">{error}</p>}

      <button
        type="button"
        disabled={deleting}
        onClick={() => void confirmDeletion()}
      >
        {deleting ? 'Deleting…' : 'Confirm image deletion'}
      </button>

      <button
        type="button"
        disabled={deleting}
        onClick={() => {
          setConfirming(false)
          setError('')
        }}
      >
        Cancel image deletion
      </button>
    </section>
  )
}