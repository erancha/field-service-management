import { useState } from 'react'
import type { CurrentUser } from '../../api/types.ts'
import { ProfileForm } from './ProfileForm.tsx'
import { hasSkippedOnboarding, markOnboardingSkipped, needsOnboarding } from './onboarding.ts'

interface OnboardingGateProps {
  user: CurrentUser
  children: React.ReactNode
}

export function OnboardingGate({ user, children }: OnboardingGateProps) {
  const [skipped, setSkipped] = useState(() => hasSkippedOnboarding(user.user_id))
  // refresh() only queues a re-fetch, so `user` still reads as incomplete right after a
  // successful save; dismissal must follow the save event itself, not needsOnboarding(user).
  const [saved, setSaved] = useState(false)

  if (!needsOnboarding(user) || skipped || saved) return <>{children}</>

  function handleSkip() {
    markOnboardingSkipped(user.user_id)
    setSkipped(true)
  }

  const isTechnician = user.role === 'TECHNICIAN'
  const requiredFields: Array<'address' | 'phone'> = isTechnician
    ? ['phone']
    : ['address', 'phone']
  const prompt = isTechnician
    ? 'Add a phone so customers can reach you if you are running late. Your address is used for dispatch and is never shown to customers.'
    : 'Add your service address and phone so technicians can find and reach you before booking.'

  return (
    <div className="page">
      <header className="page__header">
        <h2>Almost there!</h2>
      </header>
      <p>{prompt}</p>
      <ProfileForm
        user={user}
        requiredFields={requiredFields}
        onSaved={() => setSaved(true)}
        onSkip={handleSkip}
      />
    </div>
  )
}
