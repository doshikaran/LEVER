import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useMicroworldStore } from './store/useMicroworldStore'
import type { CompleteEvent } from './types'

vi.mock('./components/HonestChart', () => ({
  HonestChart: () => <div data-testid="honest-chart">chart primitive</div>,
}))
vi.mock('./components/KnobPanel', () => ({
  KnobPanel: () => <div data-testid="knob-panel">controls</div>,
}))

import App from './App'

// This is the automated substitute for the plan's manual smoke test ("generate
// a microworld, copy permalink, open the copied URL in a fresh tab"): it
// proves opening a fresh App instance with ?changeId=<id> in the URL fetches
// that exact persisted result (GET /diffs/{changeId}, the Session Ledger's
// permalink target) and renders it through the widget — not a stub, and not
// a second parallel rendering path.
const permalinked: CompleteEvent = {
  type: 'complete',
  changeId: 'permalink-target',
  widgetConfig: {
    domainPack: 'rate-limiter',
    thesis: 'Permalinked: old fixed window, new sliding window.',
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
  positionCache: {},
  sourceFiles: {},
}

class InertSocket {
  static readonly OPEN = 1
  readyState = InertSocket.OPEN
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(_url: string) {}

  close() {}
  send() {}
}

describe('App permalink open', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    useMicroworldStore.setState({ position: {}, cache: new Map() })
    window.history.pushState({}, '', '/')
  })

  it('loads the exact changeId named in the URL through the same widget-rendering path as a live diff completion', async () => {
    window.history.pushState({}, '', `/?changeId=${permalinked.changeId}`)

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes(`/diffs/${permalinked.changeId}`)) {
        return { ok: true, json: async () => permalinked }
      }
      if (url.endsWith('/diffs')) {
        // Hero 1's own startup request; deliberately never resolved via the
        // websocket below, so only the permalink target can drive the widget.
        return { ok: true, json: async () => ({ changeId: 'hero1-change-id' }) }
      }
      if (url.includes('/ledger')) {
        return { ok: true, json: async () => ({ entries: [] }) }
      }
      throw new Error(`Unexpected fetch in permalink test: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('WebSocket', InertSocket)

    render(<App />)

    expect(await screen.findByText(permalinked.widgetConfig.thesis)).toBeTruthy()
    expect(await screen.findByTestId('knob-panel')).toBeTruthy()

    const diffsCall = fetchMock.mock.calls.find(([requestUrl]) =>
      String(requestUrl).includes(`/diffs/${permalinked.changeId}`),
    )
    expect(diffsCall).toBeTruthy()

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([requestUrl]) => String(requestUrl).includes('/ledger'))).toBe(true),
    )
  })
})
