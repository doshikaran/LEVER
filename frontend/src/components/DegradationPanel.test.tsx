import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { DegradationPanel } from './DegradationPanel'
import type { DegradationEvent } from '../types'

const reasons = [
  ['unscopable', 'The change is inside a Django view requiring a live request object.'],
  ['degraded', 'Harness Engineer could not produce an executable pair after 3 attempts: live identity-provider dependency `idp.verify`.'],
  ['degraded', 'Fidelity agreement stayed below 0.85 after all three Harness Engineer attempts.'],
  ['degraded', 'I can build a model, but it depends too heavily on values I had to guess.'],
  ['degraded', 'No executable reference path or test suite was found; Lever cannot independently compare harness output to real behavior.'],
  ['degraded', 'No repository context — cannot verify a raw diff against an executable reference path.'],
] as const

function eventFor(type: DegradationEvent['type'], degradeReason: string): DegradationEvent {
  return {
    type,
    changeId: 'fixture',
    degradeReason,
    plainExplanation: 'A plain-language explanation from the scoped thesis and the one input to test manually.',
    divergenceReport: [],
    positionCache: {},
  }
}

describe('DegradationPanel', () => {
  afterEach(cleanup)

  it.each(reasons)('renders the §1.10 no-toy state for %s / %s', (type, reason) => {
    render(<DegradationPanel event={eventFor(type, reason)} />)

    expect(screen.getByRole('heading', { name: "I couldn't build a faithful model of this change." })).toBeTruthy()
    expect(screen.getByText(reason)).toBeTruthy()
    expect(screen.getByText('Plain explanation — and what to test by hand')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Zoom to the difference' })).toBeNull()
    expect(screen.queryByText('Controls')).toBeNull()
  })

  it('renders manual recipe and labeled static notes for Degradation+', () => {
    render(
      <DegradationPanel
        event={{
          ...eventFor('degraded', 'Could not verify.'),
          manualTestRecipe: ['Call with {"rps": 7} and compare admitted.'],
          staticNotes: [
            'UNVERIFIED STATIC NOTE: These notes are not a microworld and must not be treated as measured behavior.',
          ],
          proposedSpecs: [{ thesis: 'Per-tenant burst.', domainPack: 'rate-limiter' }],
        }}
      />,
    )
    expect(screen.getByTestId('manual-test-recipe').textContent).toContain('rps')
    expect(screen.getByTestId('static-notes').textContent).toContain('UNVERIFIED')
    fireEvent.click(screen.getByRole('button', { name: /Show 1 drafted scope/ }))
    expect(screen.getByTestId('scope-cards').textContent).toContain('Per-tenant burst.')
  })

  it('expands both harness and real-code values only when divergence evidence exists', () => {
    const event = eventFor('degraded', 'The harness diverged on a sampled input.')
    const withEvidence: DegradationEvent = {
      ...event,
      divergenceReport: [
        {
          position: { rps: 7 },
          version: 'head',
          observable: 'admitted',
          harness: 1,
          reference: 7,
        },
      ],
    }
    render(<DegradationPanel event={withEvidence} />)

    fireEvent.click(screen.getByRole('button', { name: '[Show me →]' }))
    expect(screen.getByRole('table')).toBeTruthy()
    expect(screen.getByText('1')).toBeTruthy()
    expect(screen.getByText('7')).toBeTruthy()
  })
})
