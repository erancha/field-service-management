import { useState } from 'react'
import { SignInButton } from '../../components/SignInButton.tsx'
import { BRAND } from '../../constants.ts'
import { withBold } from '../../utils/withBold.tsx'
import {
  DEMO_LINK,
  DEMO_MARK,
  APP_TAGLINE,
  INVITE_LINK,
  INVITE_MARK,
  LANDING_DETAILS,
  LANDING_LEAD,
  LANDING_STEPS,
  LESS,
  MORE,
  SOURCE_LINK,
} from './copy.ts'
import { demoFlashClass } from './demoFlash.ts'
import { whatsAppInviteUrl } from './invite.ts'

const SOURCE_URL = 'https://github.com/erancha/field-service-management'
// The screenshot walkthrough of one end-to-end run, published from samples/walkthrough/.
const DEMO_URL = 'https://erancha.github.io/field-service-management/samples/walkthrough/'

/**
 * The signed-out page of every role app: one card in the middle of the page, under the tab's icon,
 * the product name and the tagline, that pitches the product over the sign-in button, with a
 * toggle that adds the details. Links under the card open the visual walkthrough, invite a friend
 * or open the source. Its markup is loan-simulator's, which the shared landing.css styles.
 */
export function Landing() {
  const [expanded, setExpanded] = useState(false)
  // Opening the sign-in explanation folds the details back, so one subject is open at a time.
  const foldOnExplain = (event: { target: EventTarget }) => {
    const toggle = (event.target as Element).closest('.sign-in-why')
    if (toggle?.getAttribute('aria-expanded') === 'false') setExpanded(false)
  }
  return (
    <main className="landing">
      <div className="landing-card" onClick={foldOnExplain}>
        <h1 className="app-heading app-heading-long">
          {/* The same file as the tab's icon, so the two cannot drift apart; decorative. */}
          <img className="app-icon" src="/favicon.svg" alt="" /> {BRAND}
        </h1>
        {/* A sibling of the heading, so the heading's accessible name stays the bare title. */}
        <p className="app-tagline">{APP_TAGLINE}</p>
        {LANDING_LEAD.map((line) => (
          <p key={line} className="landing-pitch">
            {withBold(line)}
          </p>
        ))}
        <ol className="landing-steps">
          {LANDING_STEPS.map((step) => (
            <li key={step.title}>
              <span>
                <strong>{step.title}</strong>: {step.text}
              </span>
            </li>
          ))}
        </ol>
        {expanded && (
          <ul className="landing-details">
            {LANDING_DETAILS.map((detail) => (
              <li key={detail}>{withBold(detail)}</li>
            ))}
          </ul>
        )}
        <button
          type="button"
          className="landing-more"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? LESS : MORE}
        </button>
        <SignInButton />
      </div>
      <footer className="landing-links">
        <a href={DEMO_URL} className={demoFlashClass()} target="_blank" rel="noreferrer">
          <span className="link-mark" aria-hidden="true">
            {DEMO_MARK}
          </span>
          {DEMO_LINK}
        </a>
        <a href={whatsAppInviteUrl()} target="_blank" rel="noreferrer">
          <span className="link-mark" aria-hidden="true">
            {INVITE_MARK}
          </span>
          {INVITE_LINK}
        </a>
        <a href={SOURCE_URL} target="_blank" rel="noreferrer">
          {SOURCE_LINK}
        </a>
      </footer>
    </main>
  )
}
