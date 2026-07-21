import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ArenaStage } from './ArenaStage'
import type { WidgetConfig } from '../types'

const widget: WidgetConfig = {
  domainPack: 'rate-limiter',
  thesis: 'Sliding window admits more under burst.',
  controls: [],
  charts: [{
    observableId: 'admitted',
    label: 'Admitted',
    render: 'timeseries',
    compareMode: 'overlay',
    unit: 'requests',
    yAxisZeroAnchored: true,
  }],
  worldSpec: {
    genre: 'throughput',
    stage: { kind: 'arena', layout: 'full-bleed' },
    affordances: ['particles', 'dual-gates', 'surprise-marker'],
    narrationLine: 'Head admits more.',
    playHints: ['Drag load until the gates diverge.'],
  },
  initialPosition: { rps: 10 },
  surpriseMarker: {
    position: { rps: 10 },
    divergence: 0.5,
    caption: 'Head admits 2× as many requests.',
  },
  presets: [],
  fidelityBand: 'high',
  fidelityConfidence: 0.9,
  speculative: false,
  hypothesisCaveat: null,
}

describe('ArenaStage', () => {
  afterEach(() => cleanup())

  it('binds particle lanes to measured base/head counts and shows surprise caption', () => {
    render(
      <ArenaStage
        widget={widget}
        counts={{ base: 4, head: 8, divergence: 0.5 }}
        unit="requests"
      />,
    )
    expect(screen.getByTestId('arena-stage')).toBeTruthy()
    expect(screen.getByTestId('arena-gate-base')).toBeTruthy()
    expect(screen.getByTestId('arena-gate-head')).toBeTruthy()
    expect(screen.getByTestId('arena-surprise-marker').textContent).toContain('Head admits 2×')
    expect(screen.getAllByTestId('arena-particle').length).toBeGreaterThan(0)
  })
})
