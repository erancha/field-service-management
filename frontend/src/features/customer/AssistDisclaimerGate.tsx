import { useState } from 'react'
import { acceptAssistDisclaimer } from '../../api/auth.ts'
import type { CurrentUser } from '../../api/types.ts'
import { Button } from '../../components/Button.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'

interface AssistDisclaimerGateProps {
  user: CurrentUser
  children: React.ReactNode
}

interface Point {
  lead: string
  body: string
  /** Set on the two points that carry physical risk, which are styled to stand out. */
  emphasis?: boolean
}

const POINTS: Point[] = [
  {
    lead: 'Knowledge base first.',
    body:
      'The assistant retrieves from our knowledge base — internal service documentation and the ' +
      'equipment manufacturers’ user manuals, uploaded by our office — and cites the document ' +
      'each answer draws on. That material is what we stand behind.',
  },
  {
    lead: 'Model second.',
    body:
      'Where the knowledge base has no coverage, the assistant falls back on the model’s own ' +
      'training data, which has a fixed cut-off date: nothing published since, no recent recalls ' +
      'or revised procedures, and nothing specific to your installed equipment. An answer that ' +
      'cites no document is that kind of answer.',
  },
  {
    lead: 'It can be wrong.',
    body:
      'Treat every answer as something to check, not an instruction to follow. Your appliance’s ' +
      'own manual and the labels on the machine always win.',
  },
  {
    lead: 'Don’t do anything risky because the assistant suggested it.',
    body:
      'It is meant to suggest only checks that are safe to do yourself — look, listen, switch off ' +
      'and on, check a plug or a filter. Never open a sealed panel, and never touch gas, mains ' +
      'wiring, or refrigerant, or work at height. If a step feels unsafe, or you’re not sure, ' +
      'stop and book a technician. That’s what the visit is for.',
    emphasis: true,
  },
  {
    lead: 'Emergencies are not for this chat.',
    body:
      'Gas smell, smoke, sparks, or water near electrics — leave the area and call your emergency ' +
      'number.',
    emphasis: true,
  },
  {
    lead: 'What it’s good for.',
    body:
      'Ruling out the simple causes in a couple of minutes, and opening a service call and booking ' +
      'a visit when it can’t.',
  },
]

/**
 * Holds a customer at the assistant disclaimer until they confirm they have read it.
 *
 * Acceptance is persisted on the account rather than in the browser, so the disclaimer is shown
 * once per customer across every device. It is shown regardless of whether the assistant is
 * configured on this deployment: the answer must already be recorded when it is switched on.
 */
export function AssistDisclaimerGate({ user, children }: AssistDisclaimerGateProps) {
  const [understood, setUnderstood] = useState(false)
  // refresh() only queues a re-fetch, so `user` still reads as un-accepted right after a
  // successful post; dismissal must follow the post itself, not the refreshed prop.
  const [accepted, setAccepted] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (user.assist_disclaimer_accepted_at || accepted) return <>{children}</>

  async function handleContinue() {
    setSaving(true)
    setError(null)
    try {
      await acceptAssistDisclaimer()
      setAccepted(true)
    } catch {
      setError('Could not record your confirmation. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page assist-disclaimer">
      <header className="page__header">
        <h1>Before you start</h1>
      </header>

      <p>This app answers your questions with an AI assistant.</p>

      {POINTS.map((point) => (
        <p
          key={point.lead}
          className={
            point.emphasis
              ? 'assist-disclaimer__point assist-disclaimer__point--risk'
              : 'assist-disclaimer__point'
          }
        >
          <strong>{point.lead}</strong> {point.body}
        </p>
      ))}

      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <label className="assist-disclaimer__confirm">
        <input
          type="checkbox"
          checked={understood}
          onChange={(e) => setUnderstood(e.target.checked)}
        />
        I have read this and understand the assistant’s limits.
      </label>

      <Button onClick={handleContinue} disabled={!understood} loading={saving}>
        Continue
      </Button>
    </div>
  )
}
