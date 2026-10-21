import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useAuth } from '@clerk/react'

import { apiFetch } from './http'

export default function BackendSession({
  children,
}: {
  children: ReactNode
}) {
  const { getToken, userId } = useAuth()
  const [status, setStatus] = useState<
    'loading' | 'verified' | 'error'
  >('loading')
  const [message, setMessage] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    async function verify() {
      setStatus('loading')
      setMessage('')

      try {
        const token = await getToken()

        if (controller.signal.aborted) {
          return
        }

        if (!token) {
          throw new Error('Please sign out and sign in again.')
        }

        const response = await apiFetch(
          '/me',
          controller.signal,
          token,
        )

        if (!response.ok) {
          throw new Error(
            response.status === 401
              ? 'Your session could not be verified. Please sign in again.'
              : 'Unable to connect your account. Please try again.',
          )
        }

        const identity: { user_id: string } = await response.json()

        if (identity.user_id !== userId) {
          throw new Error('Account verification failed. Please sign in again.')
        }
        
        if (controller.signal.aborted) {
          return
        }

        const workspaceResponse = await apiFetch(
          '/workspace',
          controller.signal,
          token,
          { method: 'POST' },
        )

        if (!workspaceResponse.ok) {
          throw new Error(
            'Unable to prepare your workspace. Please try again.',
          )
        }

        const workspace: { workspace_id: string } =
          await workspaceResponse.json()

        if (
          typeof workspace.workspace_id !== 'string' ||
          !workspace.workspace_id.startsWith('ws_')
        ) {
          throw new Error('The workspace response was invalid.')
        }

        if (!controller.signal.aborted) {
          setStatus('verified')
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setMessage(
            error instanceof Error
              ? error.message
              : 'Unable to connect your account.',
          )
          setStatus('error')
        }
      }
    }

    void verify()
    return () => controller.abort()
  }, [getToken, userId, retry])

  if (status === 'loading') {
    return <p role="status">Connecting your account…</p>
  }

  if (status === 'error') {
    return (
      <div role="alert" style={{ padding: 24 }}>
        <p>{message}</p>
        <button onClick={() => setRetry((value) => value + 1)}>
          Retry connection
        </button>
      </div>
    )
  }

  return (
    <>
      <p role="status" style={{ padding: '0 24px' }}>
        Account connected.
      </p>
      {children}
    </>
  )
}