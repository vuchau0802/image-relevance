import { useEffect, useRef, useState } from 'react'
import {
  getImageAnalysisJob,
  startImageAnalysis,
} from './api'
import type { ImageAnalysisJob } from './api'
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

export default function AnalyzeImage({
  imageId,
}: {
  imageId: string
}) {
  const getSessionToken = useSessionToken()
  const activeRequest = useRef<AbortController | null>(null)
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState<ImageAnalysisJob | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    return () => activeRequest.current?.abort()
  }, [])

  async function analyze() {
    if (activeRequest.current) {
      return
    }

    const controller = new AbortController()
    activeRequest.current = controller
    setBusy(true)
    setError('')
    setJob(null)

    try {
      let current = await startImageAnalysis(
        imageId,
        controller.signal,
        await getSessionToken(),
      )

      while (!controller.signal.aborted) {
        setJob(current)

        if (
          current.status === 'completed' ||
          current.status === 'completed_with_errors' ||
          current.status === 'failed'
        ) {
          if (
            current.failed > 0 ||
            current.status !== 'completed'
          ) {
            setError(
              'Analysis did not complete successfully. The job needs attention.',
            )
          }
          return
        }

        await waitForPoll(controller.signal)

        if (controller.signal.aborted) {
          return
        }

        current = await getImageAnalysisJob(
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
            : 'Could not analyze this image.',
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
    <section aria-label="Image analysis" aria-busy={busy}>
      <button
        type="button"
        disabled={busy}
        onClick={() => void analyze()}
      >
        {busy ? 'Analyzing…' : 'Analyze image'}
      </button>

      {job && (
        <div role="status">
          <p>
            Analysis: {job.status}. Completed {job.completed}
            {' / '}{job.total}. Needs review: {job.needs_review}.
          </p>

          {job.status === 'queued' && (
            <p>Your image is queued for analysis.</p>
          )}

          {!busy && job.needs_review > 0 && (
            <p>
              Analysis requires review before this image can be
              prepared for matching.
            </p>
          )}

          {!busy &&
            job.status === 'completed' &&
            job.completed > 0 &&
            job.needs_review === 0 &&
            job.failed === 0 && (
              <p>
                Analysis complete. Image embedding preparation
                is still required before matching.
              </p>
            )}
        </div>
      )}

      {error && <p role="alert">{error}</p>}
    </section>
  )
}