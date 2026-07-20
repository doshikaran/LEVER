import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useMicroworldStore } from './store/useMicroworldStore'
import type { CompleteEvent, SearchTraceEvent } from './types'

vi.mock('./components/HonestChart', () => ({
  HonestChart: () => <div data-testid="honest-chart">chart primitive</div>,
}))
vi.mock('./components/KnobPanel', () => ({
  KnobPanel: () => <div data-testid="knob-panel">controls</div>,
}))

import App from './App'

const complete: CompleteEvent = {
  type: 'complete',
  changeId: 'search-trace-test',
  widgetConfig: {
    domainPack: 'rate-limiter',
    thesis: 'Measured search trace.',
    controls: [{
      id: 'rps', label: 'Requests', binding: { kind: 'driver', param: 'rps' },
      type: 'integer', domain: { min: 1, max: 100, step: 1 }, default: 3,
      scale: 'linear', unit: 'requests/s', axisRole: null,
    }],
    charts: [{ observableId: 'admitted', label: 'Admitted', render: 'timeseries', compareMode: 'overlay', unit: 'requests', yAxisZeroAnchored: true }],
    initialPosition: { rps: 3 },
    surpriseMarker: null,
    presets: [],
    fidelityBand: 'high',
    fidelityConfidence: 0.9,
    speculative: false,
    hypothesisCaveat: null,
  },
  positionCache: {
    d7daba113d562e69cfea8947090e4f86746b2466833f63b99d6334b9fe3be499: {
      base: { admitted: 3 }, head: { admitted: 6 },
    },
    ce5fbd14616cb1130b63622ff7f2b0eb37a234349831ee51a153ba19f348dcc2: {
      base: { admitted: 81 }, head: { admitted: 162 },
    },
  },
  sourceFiles: {},
}

const traceEvents: readonly SearchTraceEvent[] = [
  { type: 'search_trace', tracePoint: { position: { rps: 3 }, divergence: 0.05, phase: 'explore' } },
  { type: 'search_trace', tracePoint: { position: { rps: 81 }, divergence: 0.9, phase: 'exploit' } },
]

class SearchTraceSocket {
  static readonly OPEN = 1
  static sent = vi.fn()
  readyState = SearchTraceSocket.OPEN
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(_url: string) {
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(traceEvents[0]) } as MessageEvent<string>))
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(traceEvents[1]) } as MessageEvent<string>))
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(complete) } as MessageEvent<string>))
  }

  close() {}
  send(payload: string) { SearchTraceSocket.sent(payload) }
}

describe('App Search Trace cache-forward lookup', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    SearchTraceSocket.sent.mockReset()
    useMicroworldStore.setState({ position: {}, cache: new Map() })
  })

  it('moves to a streamed point using the existing memoized position cache', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ changeId: complete.changeId }),
    }))
    vi.stubGlobal('WebSocket', SearchTraceSocket)

    render(<App />)

    await waitFor(() => expect(screen.getAllByTestId('search-trace-point')).toHaveLength(2))
    fireEvent.click(screen.getAllByTestId('search-trace-point')[1])

    await waitFor(() => expect(screen.getByText('Cache hit — no network call')).toBeTruthy())
    expect(useMicroworldStore.getState().position).toEqual({ rps: 81 })
    expect(SearchTraceSocket.sent).not.toHaveBeenCalled()
  })
})
