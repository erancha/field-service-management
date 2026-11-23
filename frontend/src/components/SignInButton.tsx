import { useState } from 'react'
import { startGoogleSignIn } from '../api/auth.ts'
import { SignInReasons } from './SignInReasons.tsx'

/**
 * The landing page's sign-in button, which leaves for the backend's Google sign-in, with the
 * toggle under it that explains signing in with Google. While the explanation is open, the whole
 * area is framed as one panel, so the text about Google reads apart from the pitch above it.
 */
export function SignInButton() {
  const [explained, setExplained] = useState(false)
  return (
    <div className={explained ? 'sign-in sign-in-open' : 'sign-in'}>
      <button type="button" className="sign-in-button" onClick={startGoogleSignIn}>
        <span className="sign-in-mark" aria-hidden="true">G</span>
        Sign in with Google
      </button>
      <SignInReasons open={explained} onOpenChange={setExplained} />
    </div>
  )
}
