import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ClerkProvider } from '@clerk/react'

import './index.css'
import AuthGate from './AuthGate.tsx'

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

if (!publishableKey) {
  throw new Error(
    'Set VITE_CLERK_PUBLISHABLE_KEY in frontend/.env.local',
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ClerkProvider
      publishableKey={publishableKey}
      afterSignOutUrl="/"
    >
      <AuthGate />
    </ClerkProvider>
  </StrictMode>,
)