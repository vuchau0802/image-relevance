import { useEffect, useRef, useState } from 'react'
import {
  getEmbeddingJob,
  preparePostEmbedding,
  retryEmbeddingPreparation,
} from './api'
import type { EmbeddingJob } from './api'
import { useSessionToken } from './useSessionToken'

function waitForPoll(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve()
      return
    }

    function finish() {
      window.clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }

    const timer = window.setTimeout(finish, 2000)
    signal.addEventListener('abort', finish, { once: true })
  })
}

export default function PreparePost({
  postId,
  initialFailedJobId,
  onReady,
}: {
  postId: string
  initialFailedJobId?: string | null
  onReady: () => void
}) {
  const getSessionToken = useSessionToken()
  const activeRequest = useRef<AbortController | null>(null)
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState<EmbeddingJob | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    return () => activeRequest.current?.abort()
  }, [])

  const failedJobId = job === null
    ? initialFailedJobId
    : job.failed > 0 &&
        (
          job.status === 'failed' ||
          job.status === 'completed_with_errors'
        )
      ? job.job_id
      : null

  const canRetry = Boolean(failedJobId)

  async function prepare() {
    if (activeRequest.current) {
      return
    }

    const controller = new AbortController()
    activeRequest.current = controller
    setBusy(true)
    setError('')

    try {
      const token = await getSessionToken()
      if (controller.signal.aborted) return

      let current = failedJobId
        ? await retryEmbeddingPreparation(
            'post',
            postId,
            failedJobId,
            controller.signal,
            token,
          )
        : await preparePostEmbedding(
            postId,
            controller.signal,
            token,
          )

      while (!controller.signal.aborted) {
        setJob(current)

        if (current.status === 'completed') {
          onReady()
          return
        }

        if (
          current.status === 'failed' ||
          current.status === 'completed_with_errors'
        ) {
          setError(
            'Preparation failed. This job needs attention before matching.',
          )
          return
        }

        await waitForPoll(controller.signal)

        if (controller.signal.aborted) {
          return
        }

        current = await getEmbeddingJob(
          current.job_id,
          controller.signal,
          await getSessionToken(),
        )
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(
          error instanceof Error
            ? error.message
            : 'Could not prepare this post.',
        )
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
      }

      if (!controller.signal.aborted) {
        setBusy(false)
      }
    }
  }

  return (
    <section aria-label="Post preparation" aria-busy={busy}>
      <button
        type="button"
        disabled={busy}
        onClick={() => void prepare()}
      >
        {busy ? 'Preparing…' : canRetry ? 'Retry post preparation' : 'Prepare for matching'}
      </button>

      <div role="status">
        {job && (
          <p>
            Preparation: {job.status}. Completed {job.completed}
            {' / '}{job.total}.
          </p>
        )}
        {busy && job?.status === 'queued' && (
          <p>Your post is queued for processing.</p>
        )}
      </div>

      {error && <p role="alert">{error}</p>}
    </section>
  )
}