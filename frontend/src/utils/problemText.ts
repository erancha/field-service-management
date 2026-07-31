/**
 * Splits a service call's description into the parts an appointment surface labels separately.
 *
 * The triage assistant writes the description as a fault headline, an "Action items:" block of
 * "- " lines, and labelled background fields. A call opened outside that flow is free text with
 * none of that shape: it comes back whole as the problem, with no action items.
 */

const ACTION_ITEMS_HEADER = 'Action items:'
const BULLET = '- '

export interface ProblemParts {
  /** The description without the action-items block; line breaks are the author's own. */
  problem: string
  /** One entry per bullet under the header, in the order the assistant wrote them. */
  actionItems: string[]
}

export function splitProblem(description: string): ProblemParts {
  const lines = description.split('\n')
  const header = lines.indexOf(ACTION_ITEMS_HEADER)
  if (header === -1) {
    return { problem: description, actionItems: [] }
  }
  let end = header + 1
  while (end < lines.length && lines[end].startsWith(BULLET)) {
    end += 1
  }
  return {
    problem: [...lines.slice(0, header), ...lines.slice(end)].join('\n').trim(),
    actionItems: lines.slice(header + 1, end).map((line) => line.slice(BULLET.length)),
  }
}

/** The fault on its own, for a surface with one line to spend on the whole service call. */
export function problemHeadline(description: string): string {
  return description.split('\n', 1)[0]
}
