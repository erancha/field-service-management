/**
 * The words of the signed-out landing page, the same on all three role apps; **marked** words
 * show in bold. They speak to the customer, whose problem starts every visit, and the details
 * name what technicians and the back office do.
 */

/** The line under the title, short enough to stay on one line on a phone. */
export const APP_TAGLINE = 'AI-assisted service calls'

/** The pitch's opening lines: the customer's own problem first, then who else works in the app. */
export const LANDING_LEAD = [
  '**Report a fault in a chat.** An AI assistant first looks with you for a safe fix from the' +
    " company's own manuals, and books a technician's visit only when one is needed.",
  '**Customers, technicians and the back office each have an app of their own,** and every' +
    " visit lands on the technician's Google Calendar.",
]

/** The customer's way through, as numbered steps, since visitors skim prose but follow steps. */
export const LANDING_STEPS = [
  {
    title: 'Describe the fault',
    text: 'in your own words, with photos if they help.',
  },
  {
    title: 'Try a safe fix first',
    text: 'the assistant suggests safe steps from the manuals, and stops at once if it sees a risk.',
  },
  {
    title: 'Book a visit if needed',
    text:
      "on your yes, it opens a service call and offers slots from the technician's real" +
      ' availability.',
  },
]

/** What the "More" toggle adds under the pitch. */
export const LANDING_DETAILS = [
  "Bookings follow the technician's **working hours, time off, public holidays and busy times**," +
    ' and two visits never overlap.',
  'The assistant links to **the manual page** its answer comes from. The back office uploads' +
    ' those manuals.',
  '**Technicians** connect their Google Calendar, and the back office approves them before' +
    ' customers can book them.',
  '**Changes made in Google Calendar come back:** the customer is a real guest on the event, and' +
    " a visit moved there is checked against the technician's availability.",
  '**An approval or a booking shows up at once** in every open app, with a notification for' +
    ' both sides.',
]

export const MORE = 'More'
export const LESS = 'Less'

export const DEMO_LINK = 'Visual walkthrough'
/** The marks before the demo and invite links; the invite's is the same as its message's own. */
export const DEMO_MARK = '▶️'
export const INVITE_MARK = '💬'
export const INVITE_LINK = 'Invite friends on WhatsApp'
/** The invite message's paragraphs, in the voice of the friend who sends it: who it is for, how
 * it works for the customer, and where the visit lands. The page's own address follows the last
 * one. */
export const INVITE_MESSAGE = [
  'Hi! 👋 I got a recommendation for Field Service Management, an app for companies that send' +
    ' technicians to their customers, like elevator or appliance maintenance.',
  '💬 Customers report a fault in a chat. An AI assistant first looks with them for a safe fix' +
    " from the company's own manuals, and books a technician only when one is needed.",
  "📅 Every visit lands on the technician's Google Calendar, at a time they are really free.",
  'Have a look:',
]

export const SOURCE_LINK = 'Source code on GitHub'
