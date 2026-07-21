import { StrictMode } from 'react'
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useMicroworldStore } from './store/useMicroworldStore'
import { renderWithQueryClient as render } from './test/renderWithQueryClient'
import type { CompleteEvent } from './types'

vi.mock('./components/HonestChart', () => ({
  HonestChart: () => <div data-testid="honest-chart">chart primitive</div>,
}))
vi.mock('./components/KnobPanel', () => ({
  KnobPanel: () => <div data-testid="knob-panel">controls</div>,
}))

import App from './App'

// This test wraps <App /> in the real <StrictMode> (the same wrapper
// frontend/src/main.tsx uses) to empirically reproduce React 18+'s
// development-only double-invoke of every effect's setup -> cleanup -> setup
// sequence on initial mount, reusing the same component instance/state/refs
// across the two simulated setups. It exists specifically to guard the fix
// for the "permalink silently overwritten by default hero-1 kickoff" bug:
// the previous guard used a ref (isFirstHeroEffectRun) that was itself
// flipped by the effect's own first execution, so StrictMode's second
// simulated setup saw a different ref value than the first and the guard
// failed exactly under `npm run dev`. The current guard
// (hadChangeIdOnMount && !hasUserSelectedHero) uses only values that are
// stable across the double-invoke, so this test's fetch assertion holds
// under a real StrictMode remount, not just single-invoke rendering.
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

function stubFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes(`/diffs/${permalinked.changeId}`)) {
      return { ok: true, json: async () => permalinked }
    }
    if (url.endsWith('/diffs') && init?.method === 'POST') {
      return { ok: true, json: async () => ({ changeId: 'hero2-change-id' }) }
    }
    if (url.includes('/ledger')) {
      return { ok: true, json: async () => ({ entries: [] }) }
    }
    throw new Error(`Unexpected fetch in StrictMode test: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('App under real React StrictMode (double-invoked effects)', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    useMicroworldStore.setState({ position: {}, cache: new Map() })
    window.history.pushState({}, '', '/')
  })

  it('still suppresses the automatic hero-1 kickoff after StrictMode double-invokes the diff effect', async () => {
    window.history.pushState({}, '', `/?changeId=${permalinked.changeId}`)
    const fetchMock = stubFetch()
    vi.stubGlobal('WebSocket', InertSocket)

    render(
      <StrictMode>
        <App />
      </StrictMode>,
    )

    expect(await screen.findByText(permalinked.widgetConfig.thesis)).toBeTruthy()

    // StrictMode double-invokes mount effects, so the permalink fetch and the
    // ledger fetch are each expected to fire twice — that is expected and
    // harmless (both are idempotent GETs). What must NEVER happen, on either
    // of the two simulated setups, is the automatic hero-1 /diffs POST.
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(`/diffs/${permalinked.changeId}`)).length).toBeGreaterThanOrEqual(1)
    })
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/diffs'))).toBe(false)
  })

  it('still starts a fresh diff when the user explicitly switches heroes after a StrictMode-mounted permalink load', async () => {
    window.history.pushState({}, '', `/?changeId=${permalinked.changeId}`)
    const fetchMock = stubFetch()
    vi.stubGlobal('WebSocket', InertSocket)

    render(
      <StrictMode>
        <App />
      </StrictMode>,
    )

    expect(await screen.findByText(permalinked.widgetConfig.thesis)).toBeTruthy()
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/diffs'))).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: /Hero 2/ }))

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url], index) =>
        String(url).endsWith('/diffs') && fetchMock.mock.calls[index][1]?.method === 'POST',
      )).toBe(true),
    )
  })
})
