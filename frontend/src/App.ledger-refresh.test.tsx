import { cleanup, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useMicroworldStore } from './store/useMicroworldStore'
import { renderWithQueryClient as render } from './test/renderWithQueryClient'
import type { CompleteEvent, DegradationEvent } from './types'

vi.mock('./components/KnobPanel', () => ({
  KnobPanel: () => <div data-testid="knob-panel">controls</div>,
}))

import App from './App'

// Regression test: the Session Ledger sidebar's `ledgerQuery` (GET /ledger)
// only ever fetched on mount, so a newly-completed diff or prospective run
// never appeared in the sidebar without a manual page reload. applyComplete/
// applyDegradation/applyProspectiveComplete now each call
// queryClient.invalidateQueries({ queryKey: ['ledger'] }) when a run finishes,
// which — because ledgerQuery is still mounted/active — causes TanStack Query
// to refetch GET /ledger immediately. These tests prove that refetch actually
// happens rather than asserting on the invalidation call directly, since a
// refetch is the user-visible behavior the fix promises.

const complete: CompleteEvent = {
  type: 'complete',
  changeId: 'ledger-refresh-test',
  widgetConfig: {
    domainPack: 'rate-limiter',
    thesis: 'Measured difference.',
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

const degraded: DegradationEvent = {
  type: 'inert',
  changeId: 'ledger-refresh-degraded-test',
  degradeReason: 'No behavioral difference found.',
  plainExplanation: 'The modeled inputs did not reveal a behavioral difference; manually test the boundary case you care about.',
  divergenceReport: [],
  positionCache: {},
}

function socketDelivering(payload: unknown) {
  return class DeliveringSocket {
    static readonly OPEN = 1
    readyState = DeliveringSocket.OPEN
    onmessage: ((event: MessageEvent<string>) => void) | null = null
    onerror: (() => void) | null = null

    constructor(_url: string) {
      queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>))
    }

    close() {}
    send() {}
  }
}

describe('App Session Ledger refresh on run completion', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    useMicroworldStore.setState({ position: {}, cache: new Map() })
  })

  it('refetches GET /ledger after a live diff completion', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/diffs')) {
        return { ok: true, json: async () => ({ changeId: complete.changeId }) }
      }
      if (url.includes('/ledger')) {
        return { ok: true, json: async () => ({ entries: [] }) }
      }
      throw new Error(`Unexpected fetch in ledger-refresh test: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('WebSocket', socketDelivering(complete))

    render(<App />)

    const ledgerCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).includes('/ledger'))

    // The 'complete' websocket message can arrive fast enough (queued as a
    // microtask right after the mocked /diffs POST resolves) that it lands
    // before or during React Query's own mount-triggered ledger fetch, so a
    // "count before vs. after" comparison would be racy. What actually proves
    // the fix is that, once the run has visibly completed, more than the
    // single mount-time GET /ledger has fired — that second (or later) fetch
    // can only be explained by the invalidateQueries call inside applyComplete.
    expect(await screen.findByTestId('knob-panel')).toBeTruthy()
    await waitFor(() => expect(ledgerCalls().length).toBeGreaterThanOrEqual(2))
  })

  it('refetches GET /ledger after a degraded run completes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/diffs')) {
        return { ok: true, json: async () => ({ changeId: degraded.changeId }) }
      }
      if (url.includes('/ledger')) {
        return { ok: true, json: async () => ({ entries: [] }) }
      }
      throw new Error(`Unexpected fetch in ledger-refresh degraded test: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('WebSocket', socketDelivering(degraded))

    render(<App />)

    const ledgerCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).includes('/ledger'))

    // Same reasoning as the diff-completion test above: assert that more than
    // the single mount-time GET /ledger has fired once the degraded run has
    // visibly rendered, rather than racing a before/after snapshot against the
    // fast queueMicrotask-delivered websocket message.
    expect(await screen.findByText(degraded.degradeReason)).toBeTruthy()
    await waitFor(() => expect(ledgerCalls().length).toBeGreaterThanOrEqual(2))
  })
})
