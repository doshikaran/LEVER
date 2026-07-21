import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ReceiptDuel, type DuelSide } from './ReceiptDuel'

function side(changeId: string, maxDivergence: number): DuelSide {
  return {
    changeId,
    thesis: `Thesis ${changeId}`,
    domainPack: 'rate-limiter',
    fidelityBand: 'high',
    fidelityConfidence: 0.9,
    observableLabel: 'Admitted',
    unit: 'requests',
    base: { path: 'a.py', source: 'x = 1\n' },
    head: { path: 'a.py', source: 'x = 2\n' },
    frames: [
      { baseLabel: '1', headLabel: '1', divergence: 0, diverges: false, caption: null },
      { baseLabel: '4', headLabel: '8', divergence: maxDivergence, diverges: true, caption: 'diverges' },
    ],
    maxDivergence,
  }
}

describe('ReceiptDuel', () => {
  afterEach(() => cleanup())

  it('names the riskier side in the head-to-head verdict', () => {
    render(<ReceiptDuel left={side('A', 0.6)} right={side('B', 0.2)} onClose={() => {}} />)
    expect(screen.getByTestId('receipt-duel')).toBeTruthy()
    expect(screen.getByTestId('duel-verdict').textContent).toMatch(/Left change is riskier/i)
  })

  it('renders a synced scrubber when both sides have multiple frames', () => {
    render(<ReceiptDuel left={side('A', 0.6)} right={side('B', 0.2)} onClose={() => {}} />)
    expect(screen.getByTestId('duel-scrubber')).toBeTruthy()
  })
})
