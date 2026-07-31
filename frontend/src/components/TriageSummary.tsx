import type { SummaryBlock } from '../api/types.ts'

interface Props {
  blocks: SummaryBlock[]
}

/**
 * Renders the triage summary's layout as the API lays it out.
 *
 * The headings, their order, and what sits under each come from the response, so this view shows
 * the same structure as the technician's calendar event without deciding any of it — a flat run of
 * bold headings, each over a bullet list, so a reader meets one shape on either surface.
 */
export function TriageSummary({ blocks }: Props) {
  return (
    <div className="triage-summary">
      {blocks
        .filter((block) => block.bullets.length > 0 || block.fields.length > 0)
        .map((block) => (
          <div key={block.heading} className="triage-summary__block">
            <h4>{block.heading}:</h4>
            <ul>
              {block.bullets.map((bullet) => (<li key={bullet}>{bullet}</li>))}
              {block.fields.map(([label, value]) => (
                <li key={label}><b>{label}:</b> {value}</li>
              ))}
            </ul>
          </div>
        ))}
    </div>
  )
}
