import { useCallback } from 'react'
import { useAuth } from '@clerk/react'

export function useSessionToken() {
  const { getToken } = useAuth()

  return useCallback(async (): Promise<string> => {
    const token = await getToken()

    if (!token || !token.trim()) {
      throw new Error('Please sign out and sign in again.')
    }

    return token
  }, [getToken])
}
