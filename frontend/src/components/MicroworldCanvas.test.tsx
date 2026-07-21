import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const chartSpy = vi.hoisted(() => vi.fn((_props: Record<string, unknown>) => <div data-testid="honest-chart" />))

vi.mock('./HonestChart', () => ({ HonestChart: chartSpy }))

import { MicroworldCanvas } from './MicroworldCanvas'
import type { WidgetConfig } from '../types'

const widget = (speculative: boolean, hypothesisCaveat: string | null = null): WidgetConfig => ({
  domainPack: 'rate-limiter', thesis: 'Candidate comparison.', controls: [], charts: [],
  worldSpec: {
    genre: 'numeric-response',
    stage: { kind: 'curve', layout: 'stacked' },
    affordances: ['evidence-chart'],
    narrationLine: 'Candidate comparison.',
    playHints: [],
  },
  initialPosition: {}, surpriseMarker: null, presets: [], fidelityBand: 'high',
  fidelityConfidence: 1, speculative, hypothesisCaveat,
})

describe('MicroworldCanvas prospective rendering boundary', () => {
  afterEach(() => {
    cleanup()
    chartSpy.mockClear()
  })

  it('routes a speculative result to HonestChart’s prospective discriminated arm', () => {
    render(<MicroworldCanvas widget={widget(true, 'Candidate caveat.')} title="Admission" divergence={0.5} baseValue={1} headValue={2} data={[{ x: 1, base: 1, head: 2 }]} />)

    expect(screen.getByTestId('prospective-microworld')).toBeTruthy()
    expect(screen.queryByTestId('verified-microworld')).toBeNull()
    expect(chartSpy).toHaveBeenCalledTimes(1)
    expect(chartSpy.mock.calls[0]?.[0]).toMatchObject({ speculative: true, hypothesisCaveat: 'Candidate caveat.' })
    expect(chartSpy.mock.calls[0]?.[0]).not.toHaveProperty('fidelityBand')
  })

  it('uses the verified-only branch only for non-speculative code', () => {
    render(<MicroworldCanvas widget={widget(false)} title="Admission" divergence={0.5} baseValue={1} headValue={2} data={[{ x: 1, base: 1, head: 2 }]} />)

    expect(screen.getByTestId('verified-microworld')).toBeTruthy()
    expect(screen.queryByTestId('prospective-microworld')).toBeNull()
    expect(chartSpy).toHaveBeenCalledTimes(1)
    expect(chartSpy.mock.calls[0]?.[0]).toMatchObject({ fidelityBand: 'high' })
    expect(chartSpy.mock.calls[0]?.[0]).not.toHaveProperty('speculative')
  })
})
