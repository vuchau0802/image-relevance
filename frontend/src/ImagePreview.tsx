import { useSessionToken } from './useSessionToken'
import { apiFetch } from './http'
import { useEffect, useState } from 'react'

interface Props {
  imageId: string
  description: string
}

export default function ImagePreview({
  imageId,
  description,
}: Props) {
  const getSessionToken = useSessionToken()
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl: string | null = null

    async function load() {
      setUrl(null)
      setError(false)

      try {
        const response = await apiFetch(
          `/images/${encodeURIComponent(imageId)}/file`,
          controller.signal,
          await getSessionToken(),
        )

        if (!response.ok) {
          throw new Error('Image unavailable')
        }

        const blob = await response.blob()

        if (!controller.signal.aborted) {
          objectUrl = URL.createObjectURL(blob)
          setUrl(objectUrl)
        }
      } catch {
        if (!controller.signal.aborted) {
          setError(true)
        }
      }
    }

    void load()

    return () => {
      controller.abort()

      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [getSessionToken, imageId])

  if (error) {
    return <p role="status">Image preview unavailable.</p>
  }

  if (!url) {
    return <p role="status">Loading image…</p>
  }

  return (
    <img
      src={url}
      alt={description}
      onError={() => setError(true)}
      style={{
        display: 'block',
        width: '100%',
        maxHeight: 360,
        objectFit: 'contain',
        borderRadius: 8,
      }}
    />
  )
}
