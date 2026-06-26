import { getGoogleLoginUrl } from '../api/auth.ts'

export function SignInWithGoogle() {
  return (
    <a href={getGoogleLoginUrl()} className="btn btn-google">
      Sign in with Google
    </a>
  )
}
