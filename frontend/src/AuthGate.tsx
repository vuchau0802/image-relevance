import BackendSession from './BackendSession'
import {
  SignInButton,
  SignUpButton,
  UserButton,
  useAuth,
} from '@clerk/react'

import App from './App'

export default function AuthGate() {
  const { isLoaded, isSignedIn, userId } = useAuth()

  if (!isLoaded) {
    return <p role="status">Loading your session…</p>
  }

  if (!isSignedIn) {
    return (
      <main style={{ maxWidth: 600, margin: '60px auto', padding: 24 }}>
        <h1>Image Relevance</h1>
        <p>Sign in or create an account to continue.</p>

        <div style={{ display: 'flex', gap: 12 }}>
          <SignInButton mode="modal">
            <button>Sign in</button>
          </SignInButton>

          <SignUpButton mode="modal">
            <button>Create account</button>
          </SignUpButton>
        </div>
      </main>
    )
  }

  return (
    <>
      <header
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          padding: '16px 24px',
        }}
      >
        <UserButton />
      </header>

      <BackendSession key={userId}>
        <App />
      </BackendSession>
    </>
  )
}