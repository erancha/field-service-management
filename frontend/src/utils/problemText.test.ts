import { describe, expect, it } from 'vitest'
import { problemHeadline, splitProblem } from './problemText.ts'

const ASSISTANT_SUMMARY = [
  'No picture, sound present',
  '',
  'Action items:',
  '- Confirm backlight failure with the panel powered on',
  '- Bring backlight/LED strip parts',
  'Equipment: LG 86NANO91VPA television',
  'Symptoms: No picture at all while sound plays.',
].join('\n')

describe('splitProblem', () => {
  it('lifts the action items out of the problem text', () => {
    const { problem, actionItems } = splitProblem(ASSISTANT_SUMMARY)

    expect(actionItems).toEqual([
      'Confirm backlight failure with the panel powered on',
      'Bring backlight/LED strip parts',
    ])
    expect(problem).not.toContain('Action items')
    expect(problem).not.toContain('Confirm backlight failure')
  })

  it('keeps the fault and the background fields in the problem text', () => {
    const { problem } = splitProblem(ASSISTANT_SUMMARY)

    expect(problem.split('\n')[0]).toBe('No picture, sound present')
    expect(problem).toContain('Equipment: LG 86NANO91VPA television')
    expect(problem).toContain('Symptoms: No picture at all while sound plays.')
  })

  it('passes a call opened outside the triage flow through whole', () => {
    expect(splitProblem('Boiler leaks - see the photo')).toEqual({
      problem: 'Boiler leaks - see the photo',
      actionItems: [],
    })
  })
})

describe('problemHeadline', () => {
  it('is the fault alone, without the action items or the background', () => {
    expect(problemHeadline(ASSISTANT_SUMMARY)).toBe('No picture, sound present')
  })

  it('is the whole text when the description is a single line', () => {
    expect(problemHeadline('Fix boiler')).toBe('Fix boiler')
  })
})
