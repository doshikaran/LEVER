import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ComposedMicroworld } from './ComposedMicroworld'

afterEach(cleanup)

const conflictConfig = {
  changeAId: 'hero1-tenant-windows',
  changeBId: 'hero1-raised-limit',
  observableId: 'admitted',
  observableLabel: 'admitted',
  unit: 'requests',
  position: { limit_per_sec: 5, burst: 0, rps: 6, tenants: 2 },
  cells: [
    { variant: 'base' as const, observation: 5 },
    { variant: 'A' as const, observation: 10 },
    { variant: 'B' as const, observation: 10 },
    { variant: 'AB' as const, observation: 12 },
  ],
  interaction: {
    detected: true,
    additiveExpectation: 15,
    observedAB: 12,
    deviation: 3,
    tolerance: 0.01,
    caption: 'The individually executed changes do not combine additively at this input.',
  },
}

describe('ComposedMicroworld', () => {
  it('renders all four executed corners and the behavioral merge-conflict card', () => {
    render(<ComposedMicroworld config={conflictConfig} />)

    expect(screen.getByTestId('composition-cell-base').textContent).toContain('5')
    expect(screen.getByTestId('composition-cell-A').textContent).toContain('10')
    expect(screen.getByTestId('composition-cell-B').textContent).toContain('10')
    expect(screen.getByTestId('composition-cell-AB').textContent).toContain('12')
    expect(screen.getByTestId('behavioral-merge-conflict').textContent).toContain('Behavioral merge conflict')
    expect(screen.getByTestId('behavioral-merge-conflict').textContent).toContain('do not combine additively')
  })

  it('does not invent a conflict card when observed AB is additive', () => {
    render(
      <ComposedMicroworld
        config={{ ...conflictConfig, interaction: { ...conflictConfig.interaction, detected: false, caption: null } }}
      />,
    )

    expect(screen.queryByTestId('behavioral-merge-conflict')).toBeNull()
  })
})
