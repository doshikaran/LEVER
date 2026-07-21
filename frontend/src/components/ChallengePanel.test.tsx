import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ChallengePanel } from './ChallengePanel'

describe('ChallengePanel', () => {
  afterEach(() => cleanup())

  it('offers to start when inactive and fires onToggle', () => {
    const onToggle = vi.fn()
    render(
      <ChallengePanel
        active={false}
        userBest={0}
        leverBest={0.6}
        hasSurprise
        onToggle={onToggle}
        onReveal={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('challenge-start'))
    expect(onToggle).toHaveBeenCalledTimes(1)
  })

  it('hides Lever score until the user matches it, then declares a win', () => {
    const { rerender } = render(
      <ChallengePanel
        active
        userBest={0.1}
        leverBest={0.6}
        hasSurprise
        onToggle={() => {}}
        onReveal={() => {}}
      />,
    )
    expect(screen.getByTestId('challenge-user-score').textContent).toBe('10%')
    expect(screen.getByText('???')).toBeTruthy()

    rerender(
      <ChallengePanel
        active
        userBest={0.6}
        leverBest={0.6}
        hasSurprise
        onToggle={() => {}}
        onReveal={() => {}}
      />,
    )
    expect(screen.getByText(/you win/i)).toBeTruthy()
  })
})
