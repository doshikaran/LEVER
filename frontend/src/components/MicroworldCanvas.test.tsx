import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const chartSpy = vi.hoisted(() => vi.fn((_props: Record<string, unknown>) => <div data-testid="honest-chart" />))

vi.mock('./HonestChart', () => ({ HonestChart: chartSpy }))

import { MicroworldCanvas, ProspectiveCandidateRow } from './MicroworldCanvas'
import type { WidgetConfig } from '../types'

const widget = (speculative: boolean, hypothesisCaveat: string | null = null): WidgetConfig => ({
  domainPack: 'rate-limiter', thesis: 'Candidate comparison.', controls: [], charts: [],
  initialPosition: {}, surpriseMarker: null, presets: [], fidelityBand: 'high',
  fidelityConfidence: 1, speculative, hypothesisCaveat,
})

describe('MicroworldCanvas prospective rendering boundary', () => {
  afterEach(() => {
    cleanup()
    chartSpy.mockClear()
  })

  it('routes a speculative result to HonestChart’s prospective discriminated arm', () => {
    render(<MicroworldCanvas widget={widget(true, 'Candidate caveat.')} title="Admission" divergence={0.5} data={[{ x: 1, base: 1, head: 2 }]} />)

    expect(screen.getByTestId('prospective-microworld')).toBeTruthy()
    expect(screen.queryByTestId('verified-microworld')).toBeNull()
    expect(chartSpy).toHaveBeenCalledTimes(1)
    expect(chartSpy.mock.calls[0]?.[0]).toMatchObject({ speculative: true, hypothesisCaveat: 'Candidate caveat.' })
    expect(chartSpy.mock.calls[0]?.[0]).not.toHaveProperty('fidelityBand')
  })

  it('uses the verified-only branch only for non-speculative code', () => {
    render(<MicroworldCanvas widget={widget(false)} title="Admission" divergence={0.5} data={[{ x: 1, base: 1, head: 2 }]} />)

    expect(screen.getByTestId('verified-microworld')).toBeTruthy()
    expect(screen.queryByTestId('prospective-microworld')).toBeNull()
    expect(chartSpy).toHaveBeenCalledTimes(1)
    expect(chartSpy.mock.calls[0]?.[0]).toMatchObject({ fidelityBand: 'high' })
    expect(chartSpy.mock.calls[0]?.[0]).not.toHaveProperty('speculative')
  })
})

describe('ProspectiveCandidateRow (spec §6.2 — 3 candidates rendered together)', () => {
  afterEach(() => {
    cleanup()
    chartSpy.mockClear()
  })

  it('reuses the speculative-only ProspectiveMicroworld branch once per candidate, never the verified branch', () => {
    render(
      <ProspectiveCandidateRow
        candidates={[
          { key: 'c0', title: 'Candidate 1', divergence: 0.1, data: [{ x: 1, base: 1, head: 2 }], widget: widget(true, 'Caveat 0.') },
          { key: 'c1', title: 'Candidate 2', divergence: 0.2, data: [{ x: 1, base: 1, head: 3 }], widget: widget(true, 'Caveat 1.') },
          { key: 'c2', title: 'Candidate 3', divergence: 0.3, data: [{ x: 1, base: 1, head: 4 }], widget: widget(true, null) },
        ]}
      />,
    )

    expect(screen.getAllByTestId('prospective-microworld')).toHaveLength(3)
    expect(screen.queryByTestId('verified-microworld')).toBeNull()
    expect(chartSpy).toHaveBeenCalledTimes(3)
    expect(chartSpy.mock.calls.map((call) => call[0])).toMatchObject([
      { speculative: true, hypothesisCaveat: 'Caveat 0.' },
      { speculative: true, hypothesisCaveat: 'Caveat 1.' },
      { speculative: true, hypothesisCaveat: null },
    ])
  })

  it('renders nothing when given zero candidates', () => {
    render(<ProspectiveCandidateRow candidates={[]} />)
    expect(screen.queryByTestId('prospective-microworld')).toBeNull()
  })
})
