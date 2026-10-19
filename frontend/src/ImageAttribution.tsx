import { useEffect, useState } from 'react'

interface Attribution {
  image_id: string
  creator: string
  source_url: string
  license_url: string
}

function safeLink(value: string): string | undefined {
  try {
    const url = new URL(value)

    if (url.protocol === 'https:' || url.protocol === 'http:') {
      return url.href
    }
  } catch {
    return undefined
  }

  return undefined
}

export default function ImageAttribution({
  imageId,
}: {
  imageId: string
}) {
  const [data, setData] = useState<Attribution | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()

    async function load() {
      setData(null)
      setFailed(false)

      try {
        const response = await fetch(
          `/api/images/${encodeURIComponent(imageId)}/attribution`,
          {
            headers: { 'X-Tenant-ID': 'demo' },
            signal: controller.signal,
          },
        )

        if (!response.ok) {
          throw new Error('Attribution unavailable')
        }

        const attribution: Attribution = await response.json()

        if (!controller.signal.aborted) {
          setData(attribution)
        }
      } catch {
        if (!controller.signal.aborted) {
          setFailed(true)
        }
      }
    }

    void load()
    return () => controller.abort()
  }, [imageId])

  if (failed) {
    return <p>Photo credits unavailable.</p>
  }

  if (!data) {
    return <p>Loading photo credits…</p>
  }

  const source = safeLink(data.source_url)
  const license = safeLink(data.license_url)

  return (
    <p>
      Photo by {data.creator}
      {source && (
        <>
          {' · '}
          <a href={source} target="_blank" rel="noopener noreferrer">
            Source
          </a>
        </>
      )}
      {license && (
        <>
          {' · '}
          <a href={license} target="_blank" rel="noopener noreferrer">
            License
          </a>
        </>
      )}
    </p>
  )
}