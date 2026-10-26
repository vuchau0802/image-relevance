import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import { uploadImage } from './api'
import type { ImageUploadResult } from './api'
import { useSessionToken } from './useSessionToken'
import AnalyzeImage from './AnalyzeImage'

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

export default function UploadImageForm({
  onImageReady,
  onUploaded,
}: {
  onImageReady?: () => void
  onUploaded?: () => void
}) {
  const getSessionToken = useSessionToken()
  const activeRequest = useRef<AbortController | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ImageUploadResult | null>(null)

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
    const fileInput = form.elements.namedItem('file') as HTMLInputElement
    const file = fileInput.files?.[0]
    const creator = String(values.get('creator') ?? '').trim()

    setError('')
    setResult(null)

    if (!(file instanceof File) || file.size === 0) {
      setError('Choose a JPEG image.')
      return
    }

    if (file.size > MAX_UPLOAD_BYTES) {
      setError('Choose a JPEG no larger than 10 MiB.')
      return
    }

    if (!creator) {
      setError("Provide the image creator's name.")
      return
    }

    const controller = new AbortController()
    activeRequest.current = controller
    setUploading(true)

    try {
      const uploaded = await uploadImage(
        file,
        creator,
        controller.signal,
        await getSessionToken(),
      )

      if (!controller.signal.aborted) {
        form.reset()
        fileInput.value = ''
        setResult(uploaded)
        onUploaded?.()
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(
          error instanceof Error
            ? error.message
            : 'Could not upload the image.',
        )
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
      }

      if (!controller.signal.aborted) {
        setUploading(false)
      }
    }
  }

  return (
    <section aria-labelledby="upload-image-heading">
      <h2 id="upload-image-heading">Upload an image</h2>
      <p>JPEG only. Maximum 10 MiB and 20 million pixels.</p>

      <form aria-label="Upload image" onSubmit={handleSubmit}>
        <fieldset
          disabled={uploading}
          style={{ border: 0, padding: 0 }}
        >
          <label htmlFor="upload-file">JPEG image</label>
          <input
            id="upload-file"
            name="file"
            type="file"
            accept="image/jpeg"
            required
            style={{ display: 'block', marginBottom: 12 }}
          />

          <label htmlFor="upload-creator">Image creator</label>
          <input
            id="upload-creator"
            name="creator"
            required
            maxLength={200}
            style={{ display: 'block', padding: 10 }}
          />

          <button type="submit" style={{ marginTop: 12 }}>
            {uploading ? 'Uploading…' : 'Upload image'}
          </button>
        </fieldset>

        {error && <p role="alert">{error}</p>}

        {result && (
          <div role="status">
            <p>
              Image saved: {result.image_id}. Status: {result.status}.
            </p>
            {result.status === 'pending' && (
              <p>
                Upload complete. Image analysis and embedding preparation
                are still required before matching.
              </p>
            )}
          </div>
        )}

        {result && (
          <AnalyzeImage
            key={result.image_id}
            imageId={result.image_id}
            onImageReady={onImageReady}
          />
        )}
      </form>
    </section>
  )
}